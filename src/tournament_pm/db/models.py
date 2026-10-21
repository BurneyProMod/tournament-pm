"""Relational schema. Business rules that can be expressed as constraints live here too,
so the database rejects bad data even if application code has a bug."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    MetaData,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from tournament_pm.domain.models import Outcome

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class TournamentStatus(StrEnum):
    DRAFT = "draft"
    ACTIVE = "active"
    COMPLETE = "complete"


class RoundStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class EloReason(StrEnum):
    MATCH = "match"
    UNDO = "undo"
    MANUAL = "manual_adjustment"


def _enum(enum: type[StrEnum], name: str) -> Enum:
    """Store enums as VARCHAR + CHECK rather than a native Postgres ENUM type,
    so adding a value later is a simple constraint change."""
    return Enum(
        enum,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=20,
        values_callable=lambda members: [m.value for m in members],
    )


Timestamp = DateTime(timezone=True)


class Player(Base):
    __tablename__ = "player"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    elo: Mapped[int] = mapped_column(default=1000)
    archived_at: Mapped[datetime | None] = mapped_column(Timestamp)
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())

    __table_args__ = (
        CheckConstraint("elo >= 0", name="elo_non_negative"),
        CheckConstraint("btrim(name) <> ''", name="name_not_blank"),
        # Case-insensitive uniqueness: "Alex" and "alex" are the same player.
        Index("uq_player_name_lower", func.lower(name), unique=True),
    )


class Tournament(Base):
    __tablename__ = "tournament"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    status: Mapped[TournamentStatus] = mapped_column(
        _enum(TournamentStatus, "status"), default=TournamentStatus.DRAFT
    )
    best_of: Mapped[int] = mapped_column(default=3)
    default_elo_delta: Mapped[int] = mapped_column(default=25)
    rounds_planned: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())

    __table_args__ = (
        CheckConstraint("best_of > 0 AND mod(best_of, 2) = 1", name="best_of_positive_odd"),
        CheckConstraint("default_elo_delta >= 0", name="default_elo_delta_non_negative"),
        CheckConstraint(
            "rounds_planned IS NULL OR rounds_planned > 0", name="rounds_planned_positive"
        ),
    )


class TournamentEntrant(Base):
    __tablename__ = "tournament_entrant"

    tournament_id: Mapped[int] = mapped_column(
        ForeignKey("tournament.id", ondelete="CASCADE"), primary_key=True
    )
    player_id: Mapped[int] = mapped_column(
        ForeignKey("player.id", ondelete="RESTRICT"), primary_key=True
    )
    seed: Mapped[int | None]  # set when the tournament starts
    elo_at_entry: Mapped[int | None]
    dropped_at: Mapped[datetime | None] = mapped_column(Timestamp)

    __table_args__ = (
        UniqueConstraint("tournament_id", "seed"),
        CheckConstraint("seed IS NULL OR seed > 0", name="seed_positive"),
    )


class Round(Base):
    __tablename__ = "round"

    id: Mapped[int] = mapped_column(primary_key=True)
    tournament_id: Mapped[int] = mapped_column(ForeignKey("tournament.id", ondelete="CASCADE"))
    number: Mapped[int]
    status: Mapped[RoundStatus] = mapped_column(
        _enum(RoundStatus, "status"), default=RoundStatus.OPEN
    )

    __table_args__ = (
        UniqueConstraint("tournament_id", "number"),
        # Target for match's composite FK, which pins a match to its round's tournament.
        UniqueConstraint("tournament_id", "id"),
        CheckConstraint("number > 0", name="number_positive"),
    )


class Match(Base):
    __tablename__ = "match"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Duplicated from round so the composite FKs below can check that both players
    # are entrants of *this* tournament.
    tournament_id: Mapped[int]
    round_id: Mapped[int]
    player_one_id: Mapped[int]
    player_two_id: Mapped[int | None]  # NULL means BYE
    outcome: Mapped[Outcome] = mapped_column(_enum(Outcome, "outcome"), default=Outcome.PENDING)
    winner_id: Mapped[int | None]
    elo_delta: Mapped[int]
    reported_at: Mapped[datetime | None] = mapped_column(Timestamp)
    version: Mapped[int] = mapped_column(default=0)  # optimistic concurrency token

    __table_args__ = (
        ForeignKeyConstraint(
            ["tournament_id", "round_id"], ["round.tournament_id", "round.id"], ondelete="CASCADE"
        ),
        ForeignKeyConstraint(
            ["tournament_id", "player_one_id"],
            ["tournament_entrant.tournament_id", "tournament_entrant.player_id"],
        ),
        ForeignKeyConstraint(
            ["tournament_id", "player_two_id"],
            ["tournament_entrant.tournament_id", "tournament_entrant.player_id"],
        ),
        CheckConstraint("player_one_id <> player_two_id", name="distinct_players"),
        CheckConstraint(
            "winner_id IS NULL OR winner_id = player_one_id OR winner_id = player_two_id",
            name="winner_is_a_player",
        ),
        CheckConstraint("(outcome = 'bye') = (player_two_id IS NULL)", name="bye_has_one_player"),
        CheckConstraint(
            "outcome IN ('pending', 'forfeit') OR winner_id IS NOT NULL",
            name="decided_match_has_winner",
        ),
        CheckConstraint("outcome <> 'pending' OR winner_id IS NULL", name="pending_has_no_winner"),
        CheckConstraint("elo_delta >= 0", name="elo_delta_non_negative"),
        Index("ix_match_round_id", "round_id"),
    )


class Game(Base):
    __tablename__ = "game"

    match_id: Mapped[int] = mapped_column(
        ForeignKey("match.id", ondelete="CASCADE"), primary_key=True
    )
    game_number: Mapped[int] = mapped_column(primary_key=True)
    winner_id: Mapped[int] = mapped_column(ForeignKey("player.id", ondelete="RESTRICT"))

    __table_args__ = (CheckConstraint("game_number > 0", name="game_number_positive"),)


class EloChange(Base):
    """Append-only ledger. Undo adds reversing rows; nothing is updated or deleted."""

    __tablename__ = "elo_change"

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("player.id", ondelete="RESTRICT"))
    match_id: Mapped[int | None] = mapped_column(ForeignKey("match.id", ondelete="RESTRICT"))
    reason: Mapped[EloReason] = mapped_column(_enum(EloReason, "reason"))
    elo_before: Mapped[int]
    elo_after: Mapped[int]
    delta: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(Timestamp, server_default=func.now())

    __table_args__ = (
        CheckConstraint("elo_after = elo_before + delta", name="delta_matches_before_after"),
        CheckConstraint("elo_after >= 0", name="elo_after_non_negative"),
        CheckConstraint(
            "reason = 'manual_adjustment' OR match_id IS NOT NULL", name="match_reason_has_match"
        ),
        Index("ix_elo_change_player_id_created_at", "player_id", "created_at"),
        Index("ix_elo_change_match_id", "match_id"),
    )
