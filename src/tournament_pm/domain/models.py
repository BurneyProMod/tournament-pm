from dataclasses import dataclass
from enum import StrEnum

PlayerId = int


class Outcome(StrEnum):
    PENDING = "pending"
    PLAYED = "played"
    FORFEIT = "forfeit"
    BYE = "bye"


@dataclass(frozen=True, slots=True)
class Pairing:
    """One match in a generated round. `player_one` is the higher-ranked player."""

    player_one: PlayerId
    player_two: PlayerId | None  # None means BYE


@dataclass(frozen=True, slots=True)
class MatchRecord:
    """A match as the domain sees it, independent of how it is stored."""

    player_one: PlayerId
    player_two: PlayerId | None
    outcome: Outcome
    winner: PlayerId | None = None  # None while pending, or for a double forfeit
