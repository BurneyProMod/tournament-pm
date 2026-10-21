"""Match points and tiebreakers.

Scoring: a win of any kind (played, forfeit, BYE) is 1 match point; a loss is 0.
Pending matches are ignored. A double forfeit (no winner) gives neither player a point.

Ranking order:
1. Match points
2. Buchholz: sum of opponents' match points (BYEs add no opponent)
3. Head-to-head: wins against the other players still tied after 1 and 2
4. Current Elo
Players equal on all four share a rank ("1, 1, 3" competition ranking).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from tournament_pm.domain.models import MatchRecord, Outcome, PlayerId


@dataclass(slots=True)
class PlayerTally:
    points: int = 0
    opponents: list[PlayerId] = field(default_factory=list)
    had_bye: bool = False


@dataclass(frozen=True, slots=True)
class Standing:
    rank: int
    player_id: PlayerId
    points: int
    buchholz: int
    head_to_head: int
    elo: int


def tally(
    players: Iterable[PlayerId], matches: Iterable[MatchRecord]
) -> dict[PlayerId, PlayerTally]:
    tallies = {player: PlayerTally() for player in players}
    for match in matches:
        if match.outcome is Outcome.PENDING:
            continue
        if match.outcome is Outcome.BYE:
            tallies[match.player_one].had_bye = True
            tallies[match.player_one].points += 1
            continue
        assert match.player_two is not None, "only a BYE has no second player"
        tallies[match.player_one].opponents.append(match.player_two)
        tallies[match.player_two].opponents.append(match.player_one)
        if match.winner is not None:
            tallies[match.winner].points += 1
    return tallies


def compute_standings(
    elos: Mapping[PlayerId, int], matches: Sequence[MatchRecord]
) -> list[Standing]:
    """Rank every player in `elos` (player id -> current Elo) from their matches."""
    tallies = tally(elos, matches)
    buchholz = {
        player: sum(tallies[opponent].points for opponent in t.opponents)
        for player, t in tallies.items()
    }

    def tie_group(player: PlayerId) -> tuple[int, int]:
        return tallies[player].points, buchholz[player]

    head_to_head = dict.fromkeys(elos, 0)
    for match in matches:
        if match.winner is None or match.player_two is None:
            continue
        loser = match.player_two if match.winner == match.player_one else match.player_one
        if tie_group(match.winner) == tie_group(loser):
            head_to_head[match.winner] += 1

    def sort_key(player: PlayerId) -> tuple[int, int, int, int]:
        return (-tallies[player].points, -buchholz[player], -head_to_head[player], -elos[player])

    ordered = sorted(elos, key=lambda player: (sort_key(player), player))
    standings: list[Standing] = []
    for position, player in enumerate(ordered, start=1):
        if standings and sort_key(standings[-1].player_id) == sort_key(player):
            rank = standings[-1].rank
        else:
            rank = position
        standings.append(
            Standing(
                rank=rank,
                player_id=player,
                points=tallies[player].points,
                buchholz=buchholz[player],
                head_to_head=head_to_head[player],
                elo=elos[player],
            )
        )
    return standings
