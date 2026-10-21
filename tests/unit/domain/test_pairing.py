from collections.abc import Sequence

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tournament_pm.domain import pairing
from tournament_pm.domain.errors import NotEnoughPlayersError
from tournament_pm.domain.models import MatchRecord, Outcome, Pairing, PlayerId
from tournament_pm.domain.pairing import SwissPlayer, pair_round, seed_order
from tournament_pm.domain.standings import tally


def swiss_players(
    seeds: Sequence[PlayerId],
    matches: Sequence[MatchRecord] = (),
    dropped: frozenset[PlayerId] = frozenset(),
) -> list[SwissPlayer]:
    """Build pairing input the way the service layer will: from seeds and match history."""
    tallies = tally(seeds, matches)
    return [
        SwissPlayer(
            player_id=player,
            points=tallies[player].points,
            seed=seed,
            opponents=frozenset(tallies[player].opponents),
            had_bye=tallies[player].had_bye,
            dropped=player in dropped,
        )
        for seed, player in enumerate(seeds, start=1)
    ]


def as_tuples(pairings: Sequence[Pairing]) -> list[tuple[PlayerId, PlayerId | None]]:
    return [(p.player_one, p.player_two) for p in pairings]


def results(pairings: Sequence[Pairing], winners: dict[PlayerId, PlayerId]) -> list[MatchRecord]:
    """Record a round. `winners` maps player_one -> winner; BYEs need no entry."""
    return [
        MatchRecord(p.player_one, None, Outcome.BYE, p.player_one)
        if p.player_two is None
        else MatchRecord(p.player_one, p.player_two, Outcome.PLAYED, winners[p.player_one])
        for p in pairings
    ]


def is_rematch(p: Pairing, players: Sequence[SwissPlayer]) -> bool:
    by_id = {s.player_id: s for s in players}
    return p.player_two is not None and p.player_two in by_id[p.player_one].opponents


# --- Seeding and round 1 -------------------------------------------------------------


def test_seed_order_is_highest_elo_first_with_ties_by_id() -> None:
    assert seed_order({10: 1200, 11: 1500, 12: 1200, 13: 900}) == [11, 10, 12, 13]


def test_round_one_pairs_top_half_against_bottom_half() -> None:
    pairings = pair_round(swiss_players([1, 2, 3, 4, 5, 6, 7, 8]))

    assert as_tuples(pairings) == [(1, 5), (2, 6), (3, 7), (4, 8)]


def test_round_one_odd_count_gives_bye_to_lowest_seed() -> None:
    pairings = pair_round(swiss_players([1, 2, 3, 4, 5, 6, 7]))

    assert as_tuples(pairings) == [(1, 4), (2, 5), (3, 6), (7, None)]


def test_two_players_play_each_other() -> None:
    assert as_tuples(pair_round(swiss_players([1, 2]))) == [(1, 2)]


@pytest.mark.parametrize("count", [0, 1])
def test_fewer_than_two_players_is_rejected(count: int) -> None:
    with pytest.raises(NotEnoughPlayersError):
        pair_round(swiss_players(list(range(1, count + 1))))


# --- Later rounds ---------------------------------------------------------------------


def test_round_two_pairs_within_score_groups() -> None:
    seeds = [1, 2, 3, 4, 5, 6, 7, 8]
    round_one = pair_round(swiss_players(seeds))
    history = results(round_one, {1: 1, 2: 2, 3: 3, 4: 4})  # top seeds all win

    pairings = pair_round(swiss_players(seeds, history))

    assert as_tuples(pairings) == [(1, 3), (2, 4), (5, 7), (6, 8)]


def test_odd_player_in_a_score_group_floats_down() -> None:
    seeds = [1, 2, 3, 4, 5, 6]
    round_one = pair_round(swiss_players(seeds))  # (1,4) (2,5) (3,6)
    history = results(round_one, {1: 1, 2: 2, 3: 6})  # winners: 1, 2, 6

    pairings = pair_round(swiss_players(seeds, history))

    # 1-point group is [1, 2, 6]: 1 plays 2, and 6 floats down into [3, 4, 5].
    # 6 already played 3, so it takes the next one down, 4.
    assert as_tuples(pairings) == [(1, 2), (6, 4), (3, 5)]


def test_rematch_is_avoided_by_choosing_another_opponent() -> None:
    players = [
        SwissPlayer(1, points=1, seed=1, opponents=frozenset({2})),
        SwissPlayer(2, points=1, seed=2, opponents=frozenset({1})),
        SwissPlayer(3, points=0, seed=3),
        SwissPlayer(4, points=0, seed=4),
    ]

    assert as_tuples(pair_round(players)) == [(1, 3), (2, 4)]


def test_unavoidable_rematch_is_allowed() -> None:
    players = [
        SwissPlayer(1, points=1, seed=1, opponents=frozenset({2})),
        SwissPlayer(2, points=0, seed=2, opponents=frozenset({1})),
    ]

    assert as_tuples(pair_round(players)) == [(1, 2)]


def test_bye_skips_players_who_already_had_one() -> None:
    players = [
        SwissPlayer(1, points=1, seed=1),
        SwissPlayer(2, points=1, seed=2),
        SwissPlayer(3, points=1, seed=3, had_bye=True),
    ]

    pairings = pair_round(players)

    assert pairings[-1] == Pairing(2, None)


def test_dropped_player_never_gets_the_bye_while_active_players_remain() -> None:
    players = swiss_players([1, 2, 3], dropped=frozenset({3}))

    pairings = pair_round(players)

    assert pairings[-1] == Pairing(2, None)
    assert Pairing(1, 3) in pairings


def test_search_budget_exhaustion_falls_back_to_a_valid_pairing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(pairing, "MAX_SEARCH_STEPS", 0)

    pairings = pair_round(swiss_players([1, 2, 3, 4, 5]))

    assert sorted(p for pr in pairings for p in (pr.player_one, pr.player_two) if p) == [
        1,
        2,
        3,
        4,
        5,
    ]


# --- Properties over whole simulated tournaments --------------------------------------


def assert_valid_round(pairings: Sequence[Pairing], players: Sequence[SwissPlayer]) -> None:
    seated = [p.player_one for p in pairings] + [p.player_two for p in pairings if p.player_two]
    assert sorted(seated) == sorted(s.player_id for s in players), "everyone exactly once"

    byes = [p.player_one for p in pairings if p.player_two is None]
    assert len(byes) == len(players) % 2

    by_id = {s.player_id: s for s in players}
    for pr in pairings:
        if pr.player_two is not None:
            one, two = by_id[pr.player_one], by_id[pr.player_two]
            assert (one.points, -one.seed) >= (two.points, -two.seed), "player_one ranks higher"

    if byes:
        recipient = by_id[byes[0]]
        best_tier = min((s.dropped, s.had_bye) for s in players)
        assert (recipient.dropped, recipient.had_bye) == best_tier, "fairest BYE tier"


def rematch_free_pairing_exists(players: Sequence[SwissPlayer]) -> bool:
    """Brute force: is there any BYE choice (from the fairest tier) and perfect matching
    of the rest with no rematches? Only for small player counts."""

    def matchable(rest: list[SwissPlayer]) -> bool:
        if not rest:
            return True
        first, others = rest[0], rest[1:]
        return any(
            q.player_id not in first.opponents and matchable([o for o in others if o is not q])
            for q in others
        )

    if len(players) % 2 == 0:
        return matchable(list(players))
    best_tier = min((s.dropped, s.had_bye) for s in players)
    return any(
        matchable([o for o in players if o is not bye])
        for bye in players
        if (bye.dropped, bye.had_bye) == best_tier
    )


@settings(max_examples=150, deadline=None)
@given(count=st.integers(2, 48), data=st.data())
def test_swiss_invariants_hold_across_a_full_event(count: int, data: st.DataObject) -> None:
    seeds = list(range(1, count + 1))
    history: list[MatchRecord] = []
    rounds = max(1, (count - 1).bit_length())  # ceil(log2(count))

    for round_index in range(rounds):
        players = swiss_players(seeds, history)
        pairings = pair_round(players)

        assert_valid_round(pairings, players)
        # Dirac's theorem: while each player has met at most n/2 - 1 of the n players being
        # paired, a rematch-free pairing must exist, so the search has to find one.
        paired_count = count - count % 2
        if round_index <= paired_count // 2 - 1:
            assert not any(is_rematch(p, players) for p in pairings)

        winners = {
            p.player_one: data.draw(st.sampled_from([p.player_one, p.player_two]))
            for p in pairings
            if p.player_two is not None
        }
        history += results(pairings, winners)


@settings(max_examples=150, deadline=None)
@given(count=st.integers(2, 8), data=st.data())
def test_rematches_happen_only_when_unavoidable(count: int, data: st.DataObject) -> None:
    seeds = list(range(1, count + 1))
    history: list[MatchRecord] = []
    dropped: set[PlayerId] = set()

    for _ in range(count + 1):  # past a full round robin, so rematches become forced
        players = swiss_players(seeds, history, frozenset(dropped))
        pairings = pair_round(players)

        assert_valid_round(pairings, players)
        if any(is_rematch(p, players) for p in pairings):
            assert not rematch_free_pairing_exists(players)

        winners = {
            p.player_one: data.draw(st.sampled_from([p.player_one, p.player_two]))
            for p in pairings
            if p.player_two is not None
        }
        history += results(pairings, winners)
        if data.draw(st.booleans()):
            dropped.add(data.draw(st.sampled_from(seeds)))
