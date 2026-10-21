import pytest
from hypothesis import given
from hypothesis import strategies as st

from tournament_pm.domain.elo import DEFAULT_ELO_DELTA, flat_delta
from tournament_pm.domain.errors import InvalidEloDeltaError


def test_winner_gains_and_loser_loses_the_delta() -> None:
    update = flat_delta(winner_elo=1000, loser_elo=1200, delta=25)

    assert (update.winner_after, update.loser_after) == (1025, 1175)
    assert (update.winner_delta, update.loser_delta) == (25, -25)


def test_default_delta_is_25() -> None:
    assert DEFAULT_ELO_DELTA == 25
    assert flat_delta(1000, 1000).winner_delta == 25


def test_loser_stops_at_zero_but_winner_gains_full_delta() -> None:
    update = flat_delta(winner_elo=500, loser_elo=10, delta=25)

    assert update.loser_after == 0
    assert update.loser_delta == -10
    assert update.winner_delta == 25


def test_zero_delta_changes_nothing() -> None:
    update = flat_delta(1000, 900, delta=0)

    assert (update.winner_after, update.loser_after) == (1000, 900)


def test_negative_delta_is_rejected() -> None:
    with pytest.raises(InvalidEloDeltaError) as excinfo:
        flat_delta(1000, 1000, delta=-1)

    assert excinfo.value.code == "INVALID_ELO_DELTA"
    assert excinfo.value.details == {"delta": -1}


@given(
    winner=st.integers(0, 5000),
    loser=st.integers(0, 5000),
    delta=st.integers(0, 500),
)
def test_elo_never_negative_and_winner_never_loses(winner: int, loser: int, delta: int) -> None:
    update = flat_delta(winner, loser, delta)

    assert update.loser_after >= 0
    assert update.winner_delta == delta
    assert -delta <= update.loser_delta <= 0
