"""initial schema

Generated with `alembic revision --autogenerate`, then reviewed by hand:
- enum columns are VARCHAR + one named CHECK (autogenerate emitted each CHECK twice)
- added the head_to_head view, which autogenerate can't detect

Revision ID: ef21d9057e0e
Revises:
Create Date: 2026-10-21 05:55:27.942594
"""

from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision: str = "ef21d9057e0e"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

HEAD_TO_HEAD_VIEW = """
CREATE VIEW head_to_head AS
SELECT
    LEAST(player_one_id, player_two_id)    AS player_a_id,
    GREATEST(player_one_id, player_two_id) AS player_b_id,
    COUNT(*) FILTER (WHERE winner_id = LEAST(player_one_id, player_two_id))    AS wins_a,
    COUNT(*) FILTER (WHERE winner_id = GREATEST(player_one_id, player_two_id)) AS wins_b,
    COUNT(*)                                                                    AS matches
FROM match
WHERE outcome = 'played'
GROUP BY 1, 2
"""


def timestamp(name: str, *, server_default: bool = False) -> sa.Column[datetime]:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        server_default=sa.text("now()") if server_default else None,
        nullable=not server_default,
    )


def upgrade() -> None:
    op.create_table(
        "player",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("elo", sa.Integer(), nullable=False),
        timestamp("archived_at"),
        timestamp("created_at", server_default=True),
        sa.CheckConstraint("btrim(name) <> ''", name=op.f("ck_player_name_not_blank")),
        sa.CheckConstraint("elo >= 0", name=op.f("ck_player_elo_non_negative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_player")),
    )
    op.create_index(
        "uq_player_name_lower", "player", [sa.literal_column("lower(name)")], unique=True
    )

    op.create_table(
        "tournament",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("best_of", sa.Integer(), nullable=False),
        sa.Column("default_elo_delta", sa.Integer(), nullable=False),
        sa.Column("rounds_planned", sa.Integer(), nullable=True),
        timestamp("created_at", server_default=True),
        sa.CheckConstraint(
            "status IN ('draft', 'active', 'complete')", name=op.f("ck_tournament_status")
        ),
        sa.CheckConstraint(
            "best_of > 0 AND mod(best_of, 2) = 1", name=op.f("ck_tournament_best_of_positive_odd")
        ),
        sa.CheckConstraint(
            "default_elo_delta >= 0", name=op.f("ck_tournament_default_elo_delta_non_negative")
        ),
        sa.CheckConstraint(
            "rounds_planned IS NULL OR rounds_planned > 0",
            name=op.f("ck_tournament_rounds_planned_positive"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tournament")),
    )

    op.create_table(
        "round",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.CheckConstraint("status IN ('open', 'closed')", name=op.f("ck_round_status")),
        sa.CheckConstraint("number > 0", name=op.f("ck_round_number_positive")),
        sa.ForeignKeyConstraint(
            ["tournament_id"],
            ["tournament.id"],
            name=op.f("fk_round_tournament_id_tournament"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_round")),
        sa.UniqueConstraint("tournament_id", "id", name=op.f("uq_round_tournament_id_id")),
        sa.UniqueConstraint("tournament_id", "number", name=op.f("uq_round_tournament_id_number")),
    )

    op.create_table(
        "tournament_entrant",
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("elo_at_entry", sa.Integer(), nullable=True),
        timestamp("dropped_at"),
        sa.CheckConstraint(
            "seed IS NULL OR seed > 0", name=op.f("ck_tournament_entrant_seed_positive")
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["player.id"],
            name=op.f("fk_tournament_entrant_player_id_player"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["tournament_id"],
            ["tournament.id"],
            name=op.f("fk_tournament_entrant_tournament_id_tournament"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tournament_id", "player_id", name=op.f("pk_tournament_entrant")),
        sa.UniqueConstraint(
            "tournament_id", "seed", name=op.f("uq_tournament_entrant_tournament_id_seed")
        ),
    )

    op.create_table(
        "match",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tournament_id", sa.Integer(), nullable=False),
        sa.Column("round_id", sa.Integer(), nullable=False),
        sa.Column("player_one_id", sa.Integer(), nullable=False),
        sa.Column("player_two_id", sa.Integer(), nullable=True),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("winner_id", sa.Integer(), nullable=True),
        sa.Column("elo_delta", sa.Integer(), nullable=False),
        timestamp("reported_at"),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "outcome IN ('pending', 'played', 'forfeit', 'bye')", name=op.f("ck_match_outcome")
        ),
        sa.CheckConstraint(
            "(outcome = 'bye') = (player_two_id IS NULL)", name=op.f("ck_match_bye_has_one_player")
        ),
        sa.CheckConstraint(
            "outcome <> 'pending' OR winner_id IS NULL", name=op.f("ck_match_pending_has_no_winner")
        ),
        sa.CheckConstraint(
            "outcome IN ('pending', 'forfeit') OR winner_id IS NOT NULL",
            name=op.f("ck_match_decided_match_has_winner"),
        ),
        sa.CheckConstraint("elo_delta >= 0", name=op.f("ck_match_elo_delta_non_negative")),
        sa.CheckConstraint(
            "player_one_id <> player_two_id", name=op.f("ck_match_distinct_players")
        ),
        sa.CheckConstraint(
            "winner_id IS NULL OR winner_id = player_one_id OR winner_id = player_two_id",
            name=op.f("ck_match_winner_is_a_player"),
        ),
        sa.ForeignKeyConstraint(
            ["tournament_id", "player_one_id"],
            ["tournament_entrant.tournament_id", "tournament_entrant.player_id"],
            name=op.f("fk_match_tournament_id_player_one_id_tournament_entrant"),
        ),
        sa.ForeignKeyConstraint(
            ["tournament_id", "player_two_id"],
            ["tournament_entrant.tournament_id", "tournament_entrant.player_id"],
            name=op.f("fk_match_tournament_id_player_two_id_tournament_entrant"),
        ),
        sa.ForeignKeyConstraint(
            ["tournament_id", "round_id"],
            ["round.tournament_id", "round.id"],
            name=op.f("fk_match_tournament_id_round_id_round"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_match")),
    )
    op.create_index("ix_match_round_id", "match", ["round_id"], unique=False)

    op.create_table(
        "elo_change",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("match_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.String(length=20), nullable=False),
        sa.Column("elo_before", sa.Integer(), nullable=False),
        sa.Column("elo_after", sa.Integer(), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        timestamp("created_at", server_default=True),
        sa.CheckConstraint(
            "reason IN ('match', 'undo', 'manual_adjustment')", name=op.f("ck_elo_change_reason")
        ),
        sa.CheckConstraint(
            "reason = 'manual_adjustment' OR match_id IS NOT NULL",
            name=op.f("ck_elo_change_match_reason_has_match"),
        ),
        sa.CheckConstraint(
            "elo_after = elo_before + delta", name=op.f("ck_elo_change_delta_matches_before_after")
        ),
        sa.CheckConstraint("elo_after >= 0", name=op.f("ck_elo_change_elo_after_non_negative")),
        sa.ForeignKeyConstraint(
            ["match_id"],
            ["match.id"],
            name=op.f("fk_elo_change_match_id_match"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["player.id"],
            name=op.f("fk_elo_change_player_id_player"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_elo_change")),
    )
    op.create_index("ix_elo_change_match_id", "elo_change", ["match_id"], unique=False)
    op.create_index(
        "ix_elo_change_player_id_created_at",
        "elo_change",
        ["player_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "game",
        sa.Column("match_id", sa.Integer(), nullable=False),
        sa.Column("game_number", sa.Integer(), nullable=False),
        sa.Column("winner_id", sa.Integer(), nullable=False),
        sa.CheckConstraint("game_number > 0", name=op.f("ck_game_game_number_positive")),
        sa.ForeignKeyConstraint(
            ["match_id"], ["match.id"], name=op.f("fk_game_match_id_match"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["winner_id"],
            ["player.id"],
            name=op.f("fk_game_winner_id_player"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("match_id", "game_number", name=op.f("pk_game")),
    )

    op.execute(HEAD_TO_HEAD_VIEW)


def downgrade() -> None:
    op.execute("DROP VIEW head_to_head")
    op.drop_table("game")
    op.drop_index("ix_elo_change_player_id_created_at", table_name="elo_change")
    op.drop_index("ix_elo_change_match_id", table_name="elo_change")
    op.drop_table("elo_change")
    op.drop_index("ix_match_round_id", table_name="match")
    op.drop_table("match")
    op.drop_table("tournament_entrant")
    op.drop_table("round")
    op.drop_table("tournament")
    op.drop_index("uq_player_name_lower", table_name="player")
    op.drop_table("player")
