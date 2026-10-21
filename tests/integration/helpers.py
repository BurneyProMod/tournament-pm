from sqlalchemy import select

from tournament_pm.db.models import EloChange, Match, Player
from tournament_pm.db.session import SessionFactory
from tournament_pm.services.players import create_player
from tournament_pm.services.tournaments import add_entrant, create_tournament


def setup_tournament(
    factory: SessionFactory,
    elos: list[int],
    best_of: int = 3,
    delta: int = 25,
    prefix: str = "Player",
) -> tuple[int, list[int]]:
    """A draft tournament with one entrant per Elo. Returns (tournament id, player ids)."""
    tournament = create_tournament(factory, "Test Cup", best_of=best_of, default_elo_delta=delta)
    player_ids = []
    for index, elo in enumerate(elos, start=1):
        player = create_player(factory, f"{prefix} {index}", elo=elo)
        add_entrant(factory, tournament.id, player.id)
        player_ids.append(player.id)
    return tournament.id, player_ids


def matches_in_round(factory: SessionFactory, round_id: int) -> list[Match]:
    with factory() as session:
        return list(
            session.scalars(select(Match).where(Match.round_id == round_id).order_by(Match.id))
        )


def elo_of(factory: SessionFactory, player_id: int) -> int:
    with factory() as session:
        return session.get_one(Player, player_id).elo


def ledger(factory: SessionFactory) -> list[EloChange]:
    with factory() as session:
        return list(session.scalars(select(EloChange).order_by(EloChange.id)))
