from fastapi import APIRouter, Response, status

from tournament_pm.api.deps import Factory
from tournament_pm.api.errors import ERROR_RESPONSES
from tournament_pm.api.schemas import PlayerCreate, PlayerOut
from tournament_pm.db.models import Player
from tournament_pm.services import players

router = APIRouter(prefix="/players", tags=["players"], responses=ERROR_RESPONSES)


@router.post("", status_code=status.HTTP_201_CREATED, response_model=PlayerOut)
def create_player(body: PlayerCreate, factory: Factory, response: Response) -> Player:
    player = players.create_player(factory, body.name, body.elo)
    response.headers["Location"] = f"/players/{player.id}"
    return player


@router.get("", response_model=list[PlayerOut])
def list_players(factory: Factory, include_archived: bool = False) -> list[Player]:
    return players.list_players(factory, include_archived=include_archived)


@router.get("/{player_id}", response_model=PlayerOut)
def get_player(player_id: int, factory: Factory) -> Player:
    return players.get_player(factory, player_id)


@router.delete("/{player_id}", response_model=PlayerOut)
def archive_player(player_id: int, factory: Factory) -> Player:
    """Players with history are archived (soft-deleted), never removed."""
    return players.archive_player(factory, player_id)
