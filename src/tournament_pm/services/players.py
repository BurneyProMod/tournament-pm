from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from tournament_pm.db.models import Player
from tournament_pm.db.session import SessionFactory
from tournament_pm.domain.errors import DuplicatePlayerNameError, InvalidEloError
from tournament_pm.domain.players import normalize_name
from tournament_pm.services.common import get_or_404, now, violated_constraint

DEFAULT_ELO = 1000


def create_player(factory: SessionFactory, name: str, elo: int = DEFAULT_ELO) -> Player:
    name = normalize_name(name)
    if elo < 0:
        raise InvalidEloError("Elo must be 0 or greater", elo=elo)
    try:
        with factory.begin() as session:
            player = Player(name=name, elo=elo)
            session.add(player)
    except IntegrityError as exc:
        # The unique index is the source of truth; checking first would race.
        if violated_constraint(exc) == "uq_player_name_lower":
            raise DuplicatePlayerNameError(
                "A player with this name already exists", name=name
            ) from exc
        raise
    return player


def archive_player(factory: SessionFactory, player_id: int) -> Player:
    with factory.begin() as session:
        player = get_or_404(session, Player, player_id)
        if player.archived_at is None:
            player.archived_at = now()
    return player


def get_player(factory: SessionFactory, player_id: int) -> Player:
    with factory() as session:
        return get_or_404(session, Player, player_id)


def list_players(factory: SessionFactory, *, include_archived: bool = False) -> list[Player]:
    query = select(Player).order_by(Player.elo.desc(), Player.id)
    if not include_archived:
        query = query.where(Player.archived_at.is_(None))
    with factory() as session:
        return list(session.scalars(query))
