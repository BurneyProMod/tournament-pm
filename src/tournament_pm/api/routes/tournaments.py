from fastapi import APIRouter, Response, status

from tournament_pm.api.deps import Factory
from tournament_pm.api.errors import ERROR_RESPONSES
from tournament_pm.api.schemas import (
    EntrantCreate,
    EntrantOut,
    MatchOut,
    RoundOut,
    StandingOut,
    TournamentCreate,
    TournamentOut,
)
from tournament_pm.db.models import Tournament, TournamentEntrant
from tournament_pm.db.session import SessionFactory
from tournament_pm.domain.standings import Standing
from tournament_pm.services import tournaments

router = APIRouter(prefix="/tournaments", tags=["tournaments"], responses=ERROR_RESPONSES)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=TournamentOut)
def create_tournament(body: TournamentCreate, factory: Factory, response: Response) -> Tournament:
    tournament = tournaments.create_tournament(
        factory, body.name, best_of=body.best_of, default_elo_delta=body.default_elo_delta
    )
    response.headers["Location"] = f"/tournaments/{tournament.id}"
    return tournament


@router.get("/{tournament_id}", response_model=TournamentOut)
def get_tournament(tournament_id: int, factory: Factory) -> Tournament:
    return tournaments.get_tournament(factory, tournament_id)


@router.post(
    "/{tournament_id}/entrants", status_code=status.HTTP_201_CREATED, response_model=EntrantOut
)
def add_entrant(tournament_id: int, body: EntrantCreate, factory: Factory) -> TournamentEntrant:
    return tournaments.add_entrant(factory, tournament_id, body.player_id)


@router.get("/{tournament_id}/entrants", response_model=list[EntrantOut])
def list_entrants(tournament_id: int, factory: Factory) -> list[TournamentEntrant]:
    return tournaments.list_entrants(factory, tournament_id)


@router.post("/{tournament_id}/start", status_code=status.HTTP_201_CREATED)
def start_tournament(tournament_id: int, factory: Factory) -> RoundOut:
    """Lock in seeds from current Elo and pair round 1 (top half vs bottom half)."""
    round_ = tournaments.start_tournament(factory, tournament_id)
    return _round_out(factory, tournament_id, round_.number)


@router.post("/{tournament_id}/rounds", status_code=status.HTTP_201_CREATED)
def generate_next_round(tournament_id: int, factory: Factory) -> RoundOut:
    """Close the current round (all results must be in) and Swiss-pair the next one."""
    round_ = tournaments.generate_next_round(factory, tournament_id)
    return _round_out(factory, tournament_id, round_.number)


@router.get("/{tournament_id}/rounds/{number}")
def get_round(tournament_id: int, number: int, factory: Factory) -> RoundOut:
    return _round_out(factory, tournament_id, number)


@router.get("/{tournament_id}/standings", response_model=list[StandingOut])
def get_standings(tournament_id: int, factory: Factory) -> list[Standing]:
    """Ranked by match points, then Buchholz, head-to-head, and current Elo."""
    return tournaments.get_standings(factory, tournament_id)


def _round_out(factory: SessionFactory, tournament_id: int, number: int) -> RoundOut:
    round_, matches = tournaments.get_round(factory, tournament_id, number)
    return RoundOut(
        id=round_.id,
        number=round_.number,
        status=round_.status,
        matches=[MatchOut.model_validate(m) for m in matches],
    )
