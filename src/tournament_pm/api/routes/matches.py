from typing import Annotated

from fastapi import APIRouter, Query

from tournament_pm.api.deps import Factory
from tournament_pm.api.errors import ERROR_RESPONSES
from tournament_pm.api.schemas import MatchOut, ResultReport
from tournament_pm.db.models import Match
from tournament_pm.services import matches

router = APIRouter(prefix="/matches", tags=["matches"], responses=ERROR_RESPONSES)


@router.put("/{match_id}/result", response_model=MatchOut)
def report_result(match_id: int, body: ResultReport, factory: Factory) -> Match:
    """Record each game's winner and apply Elo in one transaction.

    PUT is idempotent: repeating the same result returns the stored match unchanged.
    A different result against an old `version` gets 409 STALE_VERSION.
    """
    return matches.report_result(factory, match_id, body.game_winners, body.version)


@router.delete("/{match_id}/result", response_model=MatchOut)
def undo_result(match_id: int, version: Annotated[int, Query(ge=0)], factory: Factory) -> Match:
    """Reverse a result while its round is open; Elo is restored via reversing ledger rows."""
    return matches.undo_result(factory, match_id, version)
