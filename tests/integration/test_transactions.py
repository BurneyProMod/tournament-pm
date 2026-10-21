"""Atomicity and concurrency: the guarantees the locking in services/matches.py provides."""

import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select, text

from tests.integration.helpers import elo_of, ledger, matches_in_round, setup_tournament
from tournament_pm.db.models import Game
from tournament_pm.db.session import SessionFactory
from tournament_pm.domain.errors import DomainError
from tournament_pm.domain.models import Outcome
from tournament_pm.services import matches as match_service
from tournament_pm.services.matches import report_result, undo_result
from tournament_pm.services.tournaments import generate_next_round, start_tournament


def run_together(*calls: Callable[[], object]) -> list[str]:
    """Start every call at the same moment on its own thread and connection.
    Returns "ok" or the DomainError code for each call, in order."""
    barrier = threading.Barrier(len(calls))

    def run(call: Callable[[], object]) -> str:
        barrier.wait()
        try:
            call()
        except DomainError as exc:
            return exc.code
        return "ok"

    with ThreadPoolExecutor(len(calls)) as pool:
        return list(pool.map(run, calls))


@pytest.fixture
def match_setup(factory: SessionFactory) -> tuple[int, int, int]:
    tournament_id, _ = setup_tournament(factory, [1000, 1000])
    match = matches_in_round(factory, start_tournament(factory, tournament_id).id)[0]
    assert match.player_two_id is not None
    return match.id, match.player_one_id, match.player_two_id


def test_failure_after_writes_rolls_back_everything(
    factory: SessionFactory, match_setup: tuple[int, int, int], monkeypatch: pytest.MonkeyPatch
) -> None:
    match_id, p1, p2 = match_setup

    def crash() -> None:
        raise RuntimeError("simulated crash after the games and ledger rows were flushed")

    monkeypatch.setattr(match_service, "now", crash)

    with pytest.raises(RuntimeError):
        report_result(factory, match_id, [p1, p1], expected_version=0)

    assert (elo_of(factory, p1), elo_of(factory, p2)) == (1000, 1000)
    assert ledger(factory) == []
    with factory() as session:
        assert session.scalars(select(Game)).all() == []
    match = matches_in_round(factory, 1)[0]
    assert (match.outcome, match.version) == (Outcome.PENDING, 0)


def test_conflicting_concurrent_reports_apply_exactly_one(
    factory: SessionFactory, match_setup: tuple[int, int, int]
) -> None:
    match_id, p1, p2 = match_setup

    results = run_together(
        lambda: report_result(factory, match_id, [p1, p1], expected_version=0),
        lambda: report_result(factory, match_id, [p2, p2], expected_version=0),
    )

    assert sorted(results) == ["STALE_VERSION", "ok"]
    assert len(ledger(factory)) == 2
    assert sorted([elo_of(factory, p1), elo_of(factory, p2)]) == [975, 1025]


def test_duplicate_concurrent_reports_are_idempotent(
    factory: SessionFactory, match_setup: tuple[int, int, int]
) -> None:
    match_id, p1, p2 = match_setup

    def submit() -> object:
        return report_result(factory, match_id, [p1, p1], expected_version=0)

    assert run_together(submit, submit) == ["ok", "ok"]
    assert len(ledger(factory)) == 2
    assert (elo_of(factory, p1), elo_of(factory, p2)) == (1025, 975)


@pytest.mark.parametrize("attempt", range(5))
def test_undo_racing_next_round_never_strands_a_pending_match(
    factory: SessionFactory, attempt: int
) -> None:
    tournament_id, _ = setup_tournament(factory, [1400, 1300, 1200, 1100], prefix=f"Race{attempt}")
    round_one = start_tournament(factory, tournament_id)
    for match in matches_in_round(factory, round_one.id):
        report_result(factory, match.id, [match.player_one_id] * 2, expected_version=0)
    target = matches_in_round(factory, round_one.id)[0]

    results = run_together(
        lambda: undo_result(factory, target.id, expected_version=1),
        lambda: generate_next_round(factory, tournament_id),
    )

    # Exactly one wins: either the undo (and the round stays open), or the new round
    # (and the undo is refused because the round closed).
    assert sorted(results) == ["INVALID_STATE", "ok"]
    with factory() as session:
        stranded = session.scalar(
            text(
                "SELECT count(*) FROM match JOIN round ON round.id = match.round_id"
                " WHERE round.status = 'closed' AND match.outcome = 'pending'"
            )
        )
    assert stranded == 0
