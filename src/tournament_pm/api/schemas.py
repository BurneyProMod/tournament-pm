from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from tournament_pm.db.models import RoundStatus, TournamentStatus
from tournament_pm.domain.models import Outcome


class _Out(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --- Requests -------------------------------------------------------------------------
# Field limits catch obviously bad input early; the domain layer still has the final say
# (e.g. name characters, odd best_of), so the rules live in one place.


class PlayerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100, examples=["Ada Lovelace"])
    elo: int = Field(default=1000, ge=0, le=10_000)


class TournamentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100, examples=["Friday Night Swiss"])
    best_of: int = Field(default=3, ge=1, le=99, description="Games per match; must be odd")
    default_elo_delta: int = Field(default=25, ge=0, le=1000)


class EntrantCreate(BaseModel):
    player_id: int


class ResultReport(BaseModel):
    game_winners: list[int] = Field(
        min_length=1, max_length=99, description="Winner's player id for each game, in order"
    )
    version: int = Field(ge=0, description="The match version you last saw (optimistic lock)")


# --- Responses ------------------------------------------------------------------------


class PlayerOut(_Out):
    id: int
    name: str
    elo: int
    archived_at: datetime | None
    created_at: datetime


class TournamentOut(_Out):
    id: int
    name: str
    status: TournamentStatus
    best_of: int
    default_elo_delta: int
    rounds_planned: int | None
    created_at: datetime


class EntrantOut(_Out):
    player_id: int
    seed: int | None
    elo_at_entry: int | None
    dropped_at: datetime | None


class MatchOut(_Out):
    id: int
    round_id: int
    player_one_id: int
    player_two_id: int | None
    outcome: Outcome
    winner_id: int | None
    elo_delta: int
    version: int
    reported_at: datetime | None


class RoundOut(_Out):
    id: int
    number: int
    status: RoundStatus
    matches: list[MatchOut]


class StandingOut(_Out):
    rank: int
    player_id: int
    points: int
    buchholz: int
    head_to_head: int
    elo: int


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, object] = {}


class ErrorResponse(BaseModel):
    error: ErrorBody
