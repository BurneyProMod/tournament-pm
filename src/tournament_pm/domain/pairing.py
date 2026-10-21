"""Swiss pairing.

Players are ranked by match points, then seed. Round 1 is the same algorithm with
everyone on 0 points, which gives the top-half-vs-bottom-half seeding (1 vs N/2+1).

Rules, in priority order:
1. Every player is in exactly one pairing.
2. With an odd count, one BYE goes to the lowest-ranked player in the fairest tier:
   active players without a BYE first, then players who already had one, and dropped
   players only if no active player is left.
3. No rematches, if any rematch-free pairing exists for a BYE choice from that tier.
4. Within a score group, the top half plays the bottom half; an odd player out
   floats down to the next group.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from tournament_pm.domain.errors import NotEnoughPlayersError
from tournament_pm.domain.models import Pairing, PlayerId

# Upper bound on backtracking steps before giving up on avoiding rematches.
MAX_SEARCH_STEPS = 50_000


@dataclass(frozen=True, slots=True)
class SwissPlayer:
    player_id: PlayerId
    points: int
    seed: int  # 1 = top seed
    opponents: frozenset[PlayerId] = frozenset()
    had_bye: bool = False
    dropped: bool = False


class _SearchExhaustedError(Exception):
    pass


def seed_order(elos: Mapping[PlayerId, int]) -> list[PlayerId]:
    """Player ids from top seed to bottom: highest Elo first, ties by id."""
    return sorted(elos, key=lambda player: (-elos[player], player))


def pair_round(players: Sequence[SwissPlayer]) -> list[Pairing]:
    if len(players) < 2:
        raise NotEnoughPlayersError("A round needs at least 2 players", players=len(players))

    ranked = sorted(players, key=lambda p: (-p.points, p.seed))
    bye_choices: list[SwissPlayer | None] = (
        list(_bye_candidates(ranked)) if len(ranked) % 2 else [None]
    )

    steps = [MAX_SEARCH_STEPS]
    try:
        for bye in bye_choices:
            pairs = _match([p for p in ranked if p is not bye], steps, avoid_rematches=True)
            if pairs is not None:
                return _with_bye(pairs, bye)
    except _SearchExhaustedError:
        pass

    # No rematch-free pairing exists (or none was found in budget): allow rematches.
    bye = bye_choices[0]
    pairs = _match([p for p in ranked if p is not bye], None, avoid_rematches=False)
    assert pairs is not None, "an unconstrained pairing always exists"
    return _with_bye(pairs, bye)


def _bye_candidates(ranked: Sequence[SwissPlayer]) -> list[SwissPlayer]:
    def tier(p: SwissPlayer) -> tuple[bool, bool]:
        return p.dropped, p.had_bye

    best = min(tier(p) for p in ranked)
    return [p for p in reversed(ranked) if tier(p) == best]


def _match(
    ranked: list[SwissPlayer], steps: list[int] | None, *, avoid_rematches: bool
) -> list[Pairing] | None:
    """Backtracking search: pair the top player with the first workable opponent."""
    if not ranked:
        return []
    top, rest = ranked[0], ranked[1:]
    for opponent in _preferred_opponents(top, rest):
        if avoid_rematches and (
            opponent.player_id in top.opponents or top.player_id in opponent.opponents
        ):
            continue
        if steps is not None:
            steps[0] -= 1
            if steps[0] < 0:
                raise _SearchExhaustedError
        sub = _match([p for p in rest if p is not opponent], steps, avoid_rematches=avoid_rematches)
        if sub is not None:
            return [Pairing(top.player_id, opponent.player_id), *sub]
    return None


def _preferred_opponents(top: SwissPlayer, rest: list[SwissPlayer]) -> list[SwissPlayer]:
    """Same score group first, starting halfway down it; then lower groups in rank order."""
    same = [p for p in rest if p.points == top.points]
    lower = [p for p in rest if p.points != top.points]
    half = max(0, (len(same) + 1) // 2 - 1)
    return same[half:] + same[:half][::-1] + lower


def _with_bye(pairs: list[Pairing], bye: SwissPlayer | None) -> list[Pairing]:
    return [*pairs, Pairing(bye.player_id, None)] if bye else pairs
