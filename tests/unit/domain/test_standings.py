from tournament_pm.domain.models import MatchRecord, Outcome
from tournament_pm.domain.standings import compute_standings, tally


def played(p1: int, p2: int, winner: int) -> MatchRecord:
    return MatchRecord(p1, p2, Outcome.PLAYED, winner)


def test_tally_counts_wins_opponents_and_byes() -> None:
    matches = [
        played(1, 2, winner=1),
        MatchRecord(3, None, Outcome.BYE, 3),
        MatchRecord(1, 3, Outcome.FORFEIT, 1),
        MatchRecord(2, 3, Outcome.PENDING),
    ]

    tallies = tally([1, 2, 3], matches)

    assert (tallies[1].points, tallies[1].opponents) == (2, [2, 3])
    assert (tallies[2].points, tallies[2].opponents) == (0, [1])
    assert (tallies[3].points, tallies[3].opponents, tallies[3].had_bye) == (1, [1], True)


def test_bye_counts_as_a_win_even_without_a_winner_set() -> None:
    tallies = tally([1], [MatchRecord(1, None, Outcome.BYE)])

    assert tallies[1].points == 1


def test_double_forfeit_gives_no_points() -> None:
    tallies = tally([1, 2], [MatchRecord(1, 2, Outcome.FORFEIT, winner=None)])

    assert tallies[1].points == tallies[2].points == 0
    assert tallies[1].opponents == [2]


def test_points_rank_first() -> None:
    standings = compute_standings({1: 1000, 2: 2000}, [played(1, 2, winner=1)])

    assert [(s.player_id, s.rank) for s in standings] == [(1, 1), (2, 2)]


def test_buchholz_breaks_a_points_tie() -> None:
    # 1 beat 3, 2 beat 4, 3 beat 4.
    # Points: 1 -> 1, 2 -> 1. Buchholz: 1 -> pts(3) = 1, 2 -> pts(4) = 0.
    elos = dict.fromkeys([1, 2, 3, 4], 1000)
    matches = [played(1, 3, 1), played(2, 4, 2), played(3, 4, 3)]

    by_id = {s.player_id: s for s in compute_standings(elos, matches)}

    assert by_id[1].points == by_id[2].points == 1
    assert (by_id[1].buchholz, by_id[2].buchholz) == (1, 0)
    assert by_id[1].rank < by_id[2].rank


def test_head_to_head_beats_elo_when_points_and_buchholz_tie() -> None:
    # 1 beat 2, 2 beat 3. Points: 1 -> 1, 2 -> 1. Buchholz: 1 -> 1, 2 -> 1 + 0 = 1.
    # 2 has the higher Elo, but 1 won their match.
    elos = {1: 900, 2: 1100, 3: 1000}
    matches = [played(1, 2, 1), played(2, 3, 2)]

    standings = compute_standings(elos, matches)

    assert [(s.player_id, s.rank, s.head_to_head) for s in standings[:2]] == [(1, 1, 1), (2, 2, 0)]


def test_head_to_head_cycle_leaves_players_tied() -> None:
    # 1 > 2 > 3 > 4 > 1: everyone has 1 point, Buchholz 2 and one win inside the tie.
    elos = dict.fromkeys([1, 2, 3, 4], 1000)
    matches = [played(1, 2, 1), played(2, 3, 2), played(3, 4, 3), played(1, 4, 4)]

    standings = compute_standings(elos, matches)

    assert {s.rank for s in standings} == {1}
    assert all(s.points == 1 and s.buchholz == 2 and s.head_to_head == 1 for s in standings)


def test_elo_breaks_a_tie_between_players_who_never_met() -> None:
    # 1 beat 3, 2 beat 4: 1 and 2 tie on points (1) and Buchholz (0) and never played.
    elos = {1: 900, 2: 1100, 3: 1000, 4: 1000}
    matches = [played(1, 3, 1), played(2, 4, 2)]

    standings = compute_standings(elos, matches)

    assert [s.player_id for s in standings[:2]] == [2, 1]


def test_fully_tied_players_share_a_rank() -> None:
    standings = compute_standings({1: 1000, 2: 1000, 3: 900}, [])

    assert [(s.player_id, s.rank) for s in standings] == [(1, 1), (2, 1), (3, 3)]


def test_forfeit_win_counts_toward_points_and_buchholz() -> None:
    # 2 dropped; 1 gets a forfeit win over 2, and 2's earlier win still counts for 1's Buchholz.
    elos = dict.fromkeys([1, 2, 3], 1000)
    matches = [played(2, 3, 2), MatchRecord(1, 2, Outcome.FORFEIT, 1)]

    by_id = {s.player_id: s for s in compute_standings(elos, matches)}

    assert (by_id[1].points, by_id[1].buchholz) == (1, 1)


def test_pending_matches_are_ignored() -> None:
    standings = compute_standings({1: 1000, 2: 1000}, [MatchRecord(1, 2, Outcome.PENDING)])

    assert all(s.points == 0 and s.buchholz == 0 for s in standings)
