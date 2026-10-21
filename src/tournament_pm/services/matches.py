"""Reporting and undoing results: the main transactional paths.

Locking order, the same in every function, so two transactions can never deadlock:
1. the match row (FOR UPDATE), which serializes everything touching this match
2. its round (FOR SHARE), which blocks generate_next_round from closing it meanwhile
3. both players (FOR UPDATE, ordered by id), whose Elo is read and rewritten
"""

from collections.abc import Iterable, Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from tournament_pm.db.models import (
    EloChange,
    EloReason,
    Game,
    Match,
    Player,
    Round,
    RoundStatus,
    Tournament,
)
from tournament_pm.db.session import SessionFactory
from tournament_pm.domain.elo import flat_delta
from tournament_pm.domain.errors import InvalidStateError, StaleVersionError
from tournament_pm.domain.models import Outcome, PlayerId
from tournament_pm.domain.results import match_winner
from tournament_pm.services.common import get_or_404, now


def report_result(
    factory: SessionFactory,
    match_id: int,
    game_winners: Sequence[PlayerId],
    expected_version: int,
) -> Match:
    """Record a best-of-N result and apply Elo. Retrying the same result is a no-op."""
    with factory.begin() as session:
        match = get_or_404(session, Match, match_id, lock=True)

        if match.outcome is Outcome.PLAYED and _games(session, match_id) == list(game_winners):
            return match  # idempotent retry, e.g. after a dropped response

        round_ = _lock_open_round(session, match)
        _check_version(match, expected_version)
        if match.outcome is not Outcome.PENDING:
            raise InvalidStateError(
                "Match already has a result; undo it first", outcome=match.outcome.value
            )
        assert match.player_two_id is not None, "a pending match always has two players"

        tournament = session.get_one(Tournament, round_.tournament_id)
        winner = match_winner(
            tournament.best_of, game_winners, match.player_one_id, match.player_two_id
        )
        loser = match.player_two_id if winner == match.player_one_id else match.player_one_id

        players = _lock_players(session, [winner, loser])
        update = flat_delta(players[winner].elo, players[loser].elo, match.elo_delta)
        session.add_all(
            Game(match_id=match_id, game_number=number, winner_id=game_winner)
            for number, game_winner in enumerate(game_winners, start=1)
        )
        _record_elo(session, players[winner], match_id, EloReason.MATCH, update.winner_after)
        _record_elo(session, players[loser], match_id, EloReason.MATCH, update.loser_after)

        match.outcome = Outcome.PLAYED
        match.winner_id = winner
        match.version += 1
        session.flush()  # send the writes now; a failure after this point must roll them back
        match.reported_at = now()
    return match


def undo_result(factory: SessionFactory, match_id: int, expected_version: int) -> Match:
    """Reverse a played result: append compensating ledger rows and reset the match."""
    with factory.begin() as session:
        match = get_or_404(session, Match, match_id, lock=True)
        _lock_open_round(session, match)
        _check_version(match, expected_version)
        if match.outcome is not Outcome.PLAYED:
            raise InvalidStateError(
                "Only played matches can be undone", outcome=match.outcome.value
            )

        # Net effect of this match on each player, across any earlier report/undo cycles.
        net = dict(
            session.execute(
                select(EloChange.player_id, func.sum(EloChange.delta))
                .where(EloChange.match_id == match_id)
                .group_by(EloChange.player_id)
            ).all()
        )
        players = _lock_players(session, net)
        for player_id, delta in net.items():
            player = players[player_id]
            _record_elo(session, player, match_id, EloReason.UNDO, max(0, player.elo - delta))

        session.execute(delete(Game).where(Game.match_id == match_id))
        match.outcome = Outcome.PENDING
        match.winner_id = None
        match.reported_at = None
        match.version += 1
    return match


def _lock_open_round(session: Session, match: Match) -> Round:
    round_ = get_or_404(session, Round, match.round_id, lock={"read": True})
    if round_.status is not RoundStatus.OPEN:
        raise InvalidStateError("Round is closed", round=round_.number)
    return round_


def _check_version(match: Match, expected: int) -> None:
    if match.version != expected:
        raise StaleVersionError(
            "Match was changed by someone else; reload and retry",
            expected_version=expected,
            current_version=match.version,
        )


def _lock_players(session: Session, ids: Iterable[PlayerId]) -> dict[PlayerId, Player]:
    rows = session.scalars(
        select(Player).where(Player.id.in_(list(ids))).order_by(Player.id).with_for_update()
    )
    return {player.id: player for player in rows}


def _record_elo(
    session: Session, player: Player, match_id: int, reason: EloReason, new_elo: int
) -> None:
    session.add(
        EloChange(
            player_id=player.id,
            match_id=match_id,
            reason=reason,
            elo_before=player.elo,
            elo_after=new_elo,
            delta=new_elo - player.elo,
        )
    )
    player.elo = new_elo


def _games(session: Session, match_id: int) -> list[PlayerId]:
    return list(
        session.scalars(
            select(Game.winner_id).where(Game.match_id == match_id).order_by(Game.game_number)
        )
    )
