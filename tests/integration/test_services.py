from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from tests.integration.helpers import elo_of, ledger, matches_in_round, setup_tournament
from tournament_pm.db.models import (
    EloReason,
    Game,
    Round,
    RoundStatus,
    Tournament,
    TournamentEntrant,
    TournamentStatus,
)
from tournament_pm.db.session import SessionFactory
from tournament_pm.domain.errors import (
    AlreadyEnteredError,
    DuplicatePlayerNameError,
    InvalidGameSequenceError,
    InvalidPlayerNameError,
    InvalidStateError,
    NotEnoughPlayersError,
    NotFoundError,
    StaleVersionError,
)
from tournament_pm.domain.models import Outcome
from tournament_pm.services.matches import report_result, undo_result
from tournament_pm.services.players import archive_player, create_player
from tournament_pm.services.tournaments import (
    add_entrant,
    create_tournament,
    generate_next_round,
    get_standings,
    start_tournament,
)


def report_all(factory: SessionFactory, round_id: int, *, top_wins: bool = True) -> None:
    for match in matches_in_round(factory, round_id):
        if match.outcome is Outcome.PENDING:
            assert match.player_two_id is not None
            winner = match.player_one_id if top_wins else match.player_two_id
            report_result(factory, match.id, [winner, winner], expected_version=match.version)


# --- Players and entrants -------------------------------------------------------------


def test_player_names_are_normalized_and_unique_ignoring_case(factory: SessionFactory) -> None:
    player = create_player(factory, "  Ada   Lovelace ")
    assert (player.name, player.elo) == ("Ada Lovelace", 1000)

    with pytest.raises(DuplicatePlayerNameError):
        create_player(factory, "ada lovelace")


def test_invalid_player_name_is_rejected_before_touching_the_db(factory: SessionFactory) -> None:
    with pytest.raises(InvalidPlayerNameError):
        create_player(factory, "Robert'); DROP TABLE player;--")


def test_entrants_can_only_change_in_draft(factory: SessionFactory) -> None:
    tournament_id, players = setup_tournament(factory, [1000, 1000])
    late = create_player(factory, "Latecomer")

    with pytest.raises(AlreadyEnteredError):
        add_entrant(factory, tournament_id, players[0])
    start_tournament(factory, tournament_id)
    with pytest.raises(InvalidStateError):
        add_entrant(factory, tournament_id, late.id)


def test_archived_and_unknown_players_cannot_enter(factory: SessionFactory) -> None:
    tournament = create_tournament(factory, "Cup")
    retired = archive_player(factory, create_player(factory, "Retired").id)

    with pytest.raises(InvalidStateError):
        add_entrant(factory, tournament.id, retired.id)
    with pytest.raises(NotFoundError):
        add_entrant(factory, tournament.id, 999)


# --- Starting and rounds --------------------------------------------------------------


def test_start_seeds_by_elo_and_pairs_top_half_against_bottom_half(
    factory: SessionFactory,
) -> None:
    tournament_id, (p1, p2, p3, p4) = setup_tournament(factory, [1000, 1400, 1200, 1100])

    round_one = start_tournament(factory, tournament_id)

    # Seeds by Elo: p2 (1), p3 (2), p4 (3), p1 (4) -> 1 vs 3, 2 vs 4.
    pairs = [(m.player_one_id, m.player_two_id) for m in matches_in_round(factory, round_one.id)]
    assert pairs == [(p2, p4), (p3, p1)]
    with factory() as session:
        tournament = session.get_one(Tournament, tournament_id)
        assert (tournament.status, tournament.rounds_planned) == (TournamentStatus.ACTIVE, 2)
        seeds = dict(
            session.execute(select(TournamentEntrant.player_id, TournamentEntrant.seed)).all()
        )
        assert seeds == {p2: 1, p3: 2, p4: 3, p1: 4}


def test_start_needs_two_entrants(factory: SessionFactory) -> None:
    tournament_id, _ = setup_tournament(factory, [1000])

    with pytest.raises(NotEnoughPlayersError):
        start_tournament(factory, tournament_id)


def test_odd_count_creates_a_decided_bye_with_no_elo_change(factory: SessionFactory) -> None:
    tournament_id, players = setup_tournament(factory, [1300, 1200, 1100])

    round_one = start_tournament(factory, tournament_id)

    bye = matches_in_round(factory, round_one.id)[-1]
    assert (bye.player_one_id, bye.player_two_id) == (players[2], None)
    assert (bye.outcome, bye.winner_id, bye.elo_delta) == (Outcome.BYE, players[2], 0)
    assert ledger(factory) == []


def test_next_round_requires_every_result(factory: SessionFactory) -> None:
    tournament_id, _ = setup_tournament(factory, [1000, 1000, 1000, 1000])
    round_one = start_tournament(factory, tournament_id)

    with pytest.raises(InvalidStateError, match="unreported"):
        generate_next_round(factory, tournament_id)

    report_all(factory, round_one.id)
    round_two = generate_next_round(factory, tournament_id)

    with factory() as session:
        assert session.get_one(Round, round_one.id).status is RoundStatus.CLOSED
    assert round_two.number == 2
    report_all(factory, round_two.id)
    with pytest.raises(InvalidStateError, match="All planned rounds"):
        generate_next_round(factory, tournament_id)


def test_dropped_player_forfeits_with_no_elo_change(factory: SessionFactory) -> None:
    tournament_id, players = setup_tournament(factory, [1400, 1300, 1200, 1100])
    report_all(factory, start_tournament(factory, tournament_id).id)
    with factory.begin() as session:
        entrant = session.get_one(TournamentEntrant, (tournament_id, players[0]))
        entrant.dropped_at = datetime.now(UTC)
    elo_before = elo_of(factory, players[0])

    round_two = generate_next_round(factory, tournament_id)

    forfeit = next(
        m
        for m in matches_in_round(factory, round_two.id)
        if players[0] in (m.player_one_id, m.player_two_id)
    )
    opponent = (
        forfeit.player_two_id if forfeit.player_one_id == players[0] else forfeit.player_one_id
    )
    assert (forfeit.outcome, forfeit.winner_id, forfeit.elo_delta) == (Outcome.FORFEIT, opponent, 0)
    assert elo_of(factory, players[0]) == elo_before


# --- Reporting and undoing results ----------------------------------------------------


@pytest.fixture
def match_setup(factory: SessionFactory) -> tuple[int, int, int]:
    """A started 2-player best-of-3 tournament. Returns (match id, player one, player two)."""
    tournament_id, _ = setup_tournament(factory, [1000, 1000])
    match = matches_in_round(factory, start_tournament(factory, tournament_id).id)[0]
    assert match.player_two_id is not None
    return match.id, match.player_one_id, match.player_two_id


def test_report_applies_elo_and_writes_games_and_ledger(
    factory: SessionFactory, match_setup: tuple[int, int, int]
) -> None:
    match_id, p1, p2 = match_setup

    match = report_result(factory, match_id, [p2, p1, p2], expected_version=0)

    assert (match.outcome, match.winner_id, match.version) == (Outcome.PLAYED, p2, 1)
    assert match.reported_at is not None
    assert (elo_of(factory, p1), elo_of(factory, p2)) == (975, 1025)
    assert [(e.player_id, e.reason, e.delta) for e in ledger(factory)] == [
        (p2, EloReason.MATCH, 25),
        (p1, EloReason.MATCH, -25),
    ]
    with factory() as session:
        games = session.scalars(select(Game.winner_id).order_by(Game.game_number)).all()
    assert games == [p2, p1, p2]


def test_retrying_the_same_report_is_a_no_op(
    factory: SessionFactory, match_setup: tuple[int, int, int]
) -> None:
    match_id, p1, _ = match_setup
    report_result(factory, match_id, [p1, p1], expected_version=0)

    retry = report_result(factory, match_id, [p1, p1], expected_version=0)

    assert retry.version == 1
    assert len(ledger(factory)) == 2
    assert elo_of(factory, p1) == 1025


def test_a_different_report_needs_the_current_version_and_an_undo(
    factory: SessionFactory, match_setup: tuple[int, int, int]
) -> None:
    match_id, p1, p2 = match_setup
    report_result(factory, match_id, [p1, p1], expected_version=0)

    with pytest.raises(StaleVersionError) as excinfo:
        report_result(factory, match_id, [p2, p2], expected_version=0)
    assert excinfo.value.details == {"expected_version": 0, "current_version": 1}
    with pytest.raises(InvalidStateError, match="undo it first"):
        report_result(factory, match_id, [p2, p2], expected_version=1)


def test_invalid_game_sequence_writes_nothing(
    factory: SessionFactory, match_setup: tuple[int, int, int]
) -> None:
    match_id, p1, p2 = match_setup

    with pytest.raises(InvalidGameSequenceError):
        report_result(factory, match_id, [p1, p1, p2], expected_version=0)

    assert ledger(factory) == []
    assert matches_in_round(factory, 1)[0].version == 0


def test_undo_restores_elo_and_appends_reversing_ledger_rows(
    factory: SessionFactory, match_setup: tuple[int, int, int]
) -> None:
    match_id, p1, p2 = match_setup
    report_result(factory, match_id, [p1, p1], expected_version=0)

    match = undo_result(factory, match_id, expected_version=1)

    assert (match.outcome, match.winner_id, match.reported_at, match.version) == (
        Outcome.PENDING,
        None,
        None,
        2,
    )
    assert (elo_of(factory, p1), elo_of(factory, p2)) == (1000, 1000)
    assert [(e.reason, e.delta) for e in ledger(factory)] == [
        (EloReason.MATCH, 25),
        (EloReason.MATCH, -25),
        (EloReason.UNDO, -25),
        (EloReason.UNDO, 25),
    ]
    # The match can be reported again with the new version.
    report_result(factory, match_id, [p2, p2], expected_version=2)
    assert (elo_of(factory, p1), elo_of(factory, p2)) == (975, 1025)


def test_undo_reverses_exactly_what_the_floor_allowed(factory: SessionFactory) -> None:
    tournament_id, (strong, weak) = setup_tournament(factory, [1000, 10])
    match = matches_in_round(factory, start_tournament(factory, tournament_id).id)[0]

    report_result(factory, match.id, [strong, strong], expected_version=0)
    assert elo_of(factory, weak) == 0  # lost 10, not 25
    undo_result(factory, match.id, expected_version=1)

    assert (elo_of(factory, strong), elo_of(factory, weak)) == (1000, 10)


def test_only_played_matches_in_open_rounds_can_be_undone(factory: SessionFactory) -> None:
    tournament_id, _ = setup_tournament(factory, [1300, 1200, 1100, 1000, 900])
    round_one = start_tournament(factory, tournament_id)
    bye = matches_in_round(factory, round_one.id)[-1]

    with pytest.raises(InvalidStateError, match="Only played"):
        undo_result(factory, bye.id, expected_version=0)

    report_all(factory, round_one.id)
    generate_next_round(factory, tournament_id)
    played = matches_in_round(factory, round_one.id)[0]
    with pytest.raises(InvalidStateError, match="Round is closed"):
        undo_result(factory, played.id, expected_version=played.version)


def test_unknown_match_is_not_found(factory: SessionFactory) -> None:
    with pytest.raises(NotFoundError):
        report_result(factory, 999, [1], expected_version=0)


# --- Standings ------------------------------------------------------------------------


def test_standings_rank_by_points_then_tiebreakers(factory: SessionFactory) -> None:
    tournament_id, (p1, p2, p3, p4) = setup_tournament(factory, [1400, 1300, 1200, 1100])
    report_all(factory, start_tournament(factory, tournament_id).id)  # p1 beats p3, p2 beats p4

    standings = get_standings(factory, tournament_id)

    assert [(s.player_id, s.points) for s in standings] == [(p1, 1), (p2, 1), (p3, 0), (p4, 0)]
    assert standings[0].elo == 1425
