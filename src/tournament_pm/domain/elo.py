from dataclasses import dataclass

from tournament_pm.domain.errors import InvalidEloDeltaError

DEFAULT_ELO_DELTA = 25


@dataclass(frozen=True, slots=True)
class EloUpdate:
    winner_before: int
    winner_after: int
    loser_before: int
    loser_after: int

    @property
    def winner_delta(self) -> int:
        return self.winner_after - self.winner_before

    @property
    def loser_delta(self) -> int:
        return self.loser_after - self.loser_before


def flat_delta(winner_elo: int, loser_elo: int, delta: int = DEFAULT_ELO_DELTA) -> EloUpdate:
    """Winner gains `delta`; loser loses `delta` but never drops below 0.

    The winner always gains the full delta, even when the floor limits the loser's loss,
    so ratings are not strictly zero-sum near 0.
    """
    if delta < 0:
        raise InvalidEloDeltaError("Elo delta must be 0 or greater", delta=delta)
    return EloUpdate(
        winner_before=winner_elo,
        winner_after=winner_elo + delta,
        loser_before=loser_elo,
        loser_after=max(0, loser_elo - delta),
    )
