import pytest
from hypothesis import given
from hypothesis import strategies as st

from tournament_pm.domain.errors import InvalidBestOfError, InvalidGameSequenceError
from tournament_pm.domain.results import match_winner, wins_needed

P1, P2 = 1, 2


@pytest.mark.parametrize(("best_of", "needed"), [(1, 1), (3, 2), (5, 3), (7, 4)])
def test_wins_needed(best_of: int, needed: int) -> None:
    assert wins_needed(best_of) == needed


@pytest.mark.parametrize("best_of", [0, -1, 2, 4])
def test_best_of_must_be_positive_and_odd(best_of: int) -> None:
    with pytest.raises(InvalidBestOfError):
        wins_needed(best_of)


@pytest.mark.parametrize(
    ("best_of", "games", "winner"),
    [
        (1, [P2], P2),
        (3, [P1, P1], P1),
        (3, [P1, P2, P2], P2),
        (5, [P2, P1, P2, P1, P1], P1),
    ],
)
def test_valid_sequences_return_the_winner(best_of: int, games: list[int], winner: int) -> None:
    assert match_winner(best_of, games, P1, P2) == winner


def test_game_after_match_is_decided_is_rejected() -> None:
    with pytest.raises(InvalidGameSequenceError) as excinfo:
        match_winner(3, [P1, P1, P2], P1, P2)

    assert excinfo.value.details == {"game": 3}


@pytest.mark.parametrize("games", [[], [P1], [P1, P2]])
def test_undecided_match_is_rejected(games: list[int]) -> None:
    with pytest.raises(InvalidGameSequenceError, match="not decided"):
        match_winner(3, games, P1, P2)


def test_unknown_game_winner_is_rejected() -> None:
    with pytest.raises(InvalidGameSequenceError) as excinfo:
        match_winner(3, [P1, 99], P1, P2)

    assert excinfo.value.details == {"game": 2, "winner_id": 99}


@st.composite
def decided_match(draw: st.DrawFn) -> tuple[int, list[int], int]:
    """A random best-of-N and a game sequence that ends exactly when someone clinches."""
    best_of = draw(st.sampled_from([1, 3, 5, 7, 9]))
    needed = best_of // 2 + 1
    wins = {P1: 0, P2: 0}
    games: list[int] = []
    while max(wins.values()) < needed:
        game_winner = draw(st.sampled_from([P1, P2]))
        wins[game_winner] += 1
        games.append(game_winner)
    return best_of, games, max(wins, key=wins.__getitem__)


@given(decided_match())
def test_any_decided_sequence_is_accepted(case: tuple[int, list[int], int]) -> None:
    best_of, games, expected = case

    assert match_winner(best_of, games, P1, P2) == expected


@given(decided_match(), st.sampled_from([P1, P2]))
def test_any_extra_game_is_rejected(case: tuple[int, list[int], int], extra: int) -> None:
    best_of, games, _ = case

    with pytest.raises(InvalidGameSequenceError):
        match_winner(best_of, [*games, extra], P1, P2)
