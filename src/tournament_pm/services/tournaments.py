from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tournament_pm.db.models import (
    Match,
    Player,
    Round,
    RoundStatus,
    Tournament,
    TournamentEntrant,
    TournamentStatus,
)
from tournament_pm.db.session import SessionFactory
from tournament_pm.domain.elo import DEFAULT_ELO_DELTA
from tournament_pm.domain.errors import (
    AlreadyEnteredError,
    InvalidEloDeltaError,
    InvalidStateError,
    NotEnoughPlayersError,
    NotFoundError,
)
from tournament_pm.domain.models import MatchRecord, Outcome
from tournament_pm.domain.pairing import SwissPlayer, pair_round, seed_order
from tournament_pm.domain.results import wins_needed
from tournament_pm.domain.standings import Standing, compute_standings, tally
from tournament_pm.services.common import get_or_404, now


def create_tournament(
    factory: SessionFactory,
    name: str,
    best_of: int = 3,
    default_elo_delta: int = DEFAULT_ELO_DELTA,
) -> Tournament:
    wins_needed(best_of)  # raises InvalidBestOfError
    if default_elo_delta < 0:
        raise InvalidEloDeltaError("Elo delta must be 0 or greater", delta=default_elo_delta)
    with factory.begin() as session:
        tournament = Tournament(name=name, best_of=best_of, default_elo_delta=default_elo_delta)
        session.add(tournament)
    return tournament


def add_entrant(factory: SessionFactory, tournament_id: int, player_id: int) -> TournamentEntrant:
    with factory.begin() as session:
        # Lock the tournament so a concurrent start can't slip in between check and insert.
        tournament = get_or_404(session, Tournament, tournament_id, lock=True)
        _require_status(tournament, TournamentStatus.DRAFT, "Entrants can only change in draft")
        player = get_or_404(session, Player, player_id)
        if player.archived_at is not None:
            raise InvalidStateError("Archived players can't enter tournaments", player_id=player_id)
        if session.get(TournamentEntrant, (tournament_id, player_id)) is not None:
            raise AlreadyEnteredError("Player is already entered", player_id=player_id)
        entrant = TournamentEntrant(tournament_id=tournament_id, player_id=player_id)
        session.add(entrant)
    return entrant


def start_tournament(factory: SessionFactory, tournament_id: int) -> Round:
    """Fix seeds from current Elo, then create round 1, all in one transaction."""
    with factory.begin() as session:
        tournament = get_or_404(session, Tournament, tournament_id, lock=True)
        _require_status(tournament, TournamentStatus.DRAFT, "Tournament has already started")

        rows = session.execute(
            select(TournamentEntrant, Player.elo)
            .join(Player, Player.id == TournamentEntrant.player_id)
            .where(TournamentEntrant.tournament_id == tournament_id)
        ).all()
        if len(rows) < 2:
            raise NotEnoughPlayersError(
                "A tournament needs at least 2 entrants", entrants=len(rows)
            )

        elos = {entrant.player_id: elo for entrant, elo in rows}
        seeds = {player: seed for seed, player in enumerate(seed_order(elos), start=1)}
        for entrant, elo in rows:
            entrant.seed = seeds[entrant.player_id]
            entrant.elo_at_entry = elo

        tournament.status = TournamentStatus.ACTIVE
        tournament.rounds_planned = max(1, (len(rows) - 1).bit_length())  # ceil(log2(n))
        return _create_round(session, tournament, number=1)


def generate_next_round(factory: SessionFactory, tournament_id: int) -> Round:
    """Close the current round (every match must have a result) and pair the next one."""
    with factory.begin() as session:
        tournament = get_or_404(session, Tournament, tournament_id, lock=True)
        _require_status(tournament, TournamentStatus.ACTIVE, "Tournament is not active")

        current = session.scalars(
            select(Round)
            .where(Round.tournament_id == tournament_id)
            .order_by(Round.number.desc())
            .limit(1)
            # FOR UPDATE conflicts with the FOR SHARE taken by report/undo, so a result
            # can't be undone between our "no pending matches" check and the close.
            .with_for_update()
        ).one()
        pending = session.scalar(
            select(func.count())
            .select_from(Match)
            .where(Match.round_id == current.id, Match.outcome == Outcome.PENDING)
        )
        if pending:
            raise InvalidStateError(
                f"Round {current.number} still has unreported matches", pending=pending
            )
        assert tournament.rounds_planned is not None
        if current.number >= tournament.rounds_planned:
            raise InvalidStateError(
                "All planned rounds have been played", rounds_planned=tournament.rounds_planned
            )

        current.status = RoundStatus.CLOSED
        return _create_round(session, tournament, number=current.number + 1)


def get_standings(factory: SessionFactory, tournament_id: int) -> list[Standing]:
    with factory() as session:
        get_or_404(session, Tournament, tournament_id)
        elos = dict(
            session.execute(
                select(Player.id, Player.elo)
                .join(TournamentEntrant, TournamentEntrant.player_id == Player.id)
                .where(TournamentEntrant.tournament_id == tournament_id)
            ).all()
        )
        return compute_standings(elos, _match_records(session, tournament_id))


def _create_round(session: Session, tournament: Tournament, number: int) -> Round:
    entrants = session.scalars(
        select(TournamentEntrant).where(TournamentEntrant.tournament_id == tournament.id)
    ).all()
    tallies = tally((e.player_id for e in entrants), _match_records(session, tournament.id))
    dropped = {e.player_id for e in entrants if e.dropped_at is not None}

    players = []
    for entrant in entrants:
        assert entrant.seed is not None, "seeds are set when the tournament starts"
        record = tallies[entrant.player_id]
        players.append(
            SwissPlayer(
                player_id=entrant.player_id,
                points=record.points,
                seed=entrant.seed,
                opponents=frozenset(record.opponents),
                had_bye=record.had_bye,
                dropped=entrant.player_id in dropped,
            )
        )
    pairings = pair_round(players)

    round_ = Round(tournament_id=tournament.id, number=number, status=RoundStatus.OPEN)
    session.add(round_)
    session.flush()  # assigns round_.id

    for pairing in pairings:
        match = Match(
            tournament_id=tournament.id,
            round_id=round_.id,
            player_one_id=pairing.player_one,
            player_two_id=pairing.player_two,
            elo_delta=tournament.default_elo_delta,
        )
        if pairing.player_two is None:
            _decide_without_play(match, Outcome.BYE, winner=pairing.player_one)
        elif dropped & {pairing.player_one, pairing.player_two}:
            # A dropped player forfeits; if both dropped, nobody wins.
            active = {pairing.player_one, pairing.player_two} - dropped
            _decide_without_play(match, Outcome.FORFEIT, winner=next(iter(active), None))
        session.add(match)
    return round_


def _decide_without_play(match: Match, outcome: Outcome, winner: int | None) -> None:
    """BYEs and forfeits are decided at creation and never move Elo."""
    match.outcome = outcome
    match.winner_id = winner
    match.elo_delta = 0
    match.reported_at = now()


def _match_records(session: Session, tournament_id: int) -> list[MatchRecord]:
    rows = session.execute(
        select(Match.player_one_id, Match.player_two_id, Match.outcome, Match.winner_id)
        .where(Match.tournament_id == tournament_id)
        .order_by(Match.id)
    ).all()
    return [MatchRecord(p1, p2, outcome, winner) for p1, p2, outcome, winner in rows]


def _require_status(tournament: Tournament, status: TournamentStatus, message: str) -> None:
    if tournament.status is not status:
        raise InvalidStateError(message, status=tournament.status.value)


def get_tournament(factory: SessionFactory, tournament_id: int) -> Tournament:
    with factory() as session:
        return get_or_404(session, Tournament, tournament_id)


def list_entrants(factory: SessionFactory, tournament_id: int) -> list[TournamentEntrant]:
    with factory() as session:
        get_or_404(session, Tournament, tournament_id)
        return list(
            session.scalars(
                select(TournamentEntrant)
                .where(TournamentEntrant.tournament_id == tournament_id)
                .order_by(TournamentEntrant.seed, TournamentEntrant.player_id)
            )
        )


def get_round(
    factory: SessionFactory, tournament_id: int, number: int
) -> tuple[Round, list[Match]]:
    with factory() as session:
        round_ = session.scalar(
            select(Round).where(Round.tournament_id == tournament_id, Round.number == number)
        )
        if round_ is None:
            raise NotFoundError("Round not found", tournament_id=tournament_id, number=number)
        matches = session.scalars(
            select(Match).where(Match.round_id == round_.id).order_by(Match.id)
        ).all()
        return round_, list(matches)
