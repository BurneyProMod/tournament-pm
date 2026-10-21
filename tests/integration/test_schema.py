"""The database itself enforces the rules, independent of application code."""

import pytest
from alembic import command
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from tests.integration.conftest import alembic_config
from tournament_pm.db.session import SessionFactory


def insert(engine: Engine, sql: str) -> None:
    with engine.begin() as conn:
        conn.execute(text(sql))


def violated(engine: Engine, sql: str) -> str:
    """Run `sql`, expect an IntegrityError, and return the violated constraint's name."""
    with pytest.raises(IntegrityError) as excinfo:
        insert(engine, sql)
    return str(excinfo.value.orig.diag.constraint_name)  # type: ignore[union-attr]


@pytest.fixture
def seeded(engine: Engine, factory: SessionFactory) -> Engine:
    """Two entered players (1, 2), one outsider (3), and an open round 1 of tournament 1."""
    insert(
        engine,
        """
        INSERT INTO player (name, elo) VALUES ('A', 1000), ('B', 1000), ('Outsider', 1000);
        INSERT INTO tournament (name, status, best_of, default_elo_delta)
            VALUES ('Cup', 'active', 3, 25);
        INSERT INTO tournament_entrant (tournament_id, player_id) VALUES (1, 1), (1, 2);
        INSERT INTO round (tournament_id, number, status) VALUES (1, 1, 'open');
        """,
    )
    return engine


def match_sql(p1: int, p2: str, outcome: str = "pending", winner: str = "NULL") -> str:
    return (
        "INSERT INTO match (tournament_id, round_id, player_one_id, player_two_id,"
        " outcome, winner_id, elo_delta, version)"
        f" VALUES (1, 1, {p1}, {p2}, '{outcome}', {winner}, 25, 0)"
    )


def test_migration_downgrades_and_upgrades_cleanly(engine: Engine) -> None:
    command.downgrade(alembic_config(), "base")
    command.upgrade(alembic_config(), "head")


def test_elo_cannot_go_negative(seeded: Engine) -> None:
    assert (
        violated(seeded, "UPDATE player SET elo = -1 WHERE id = 1") == "ck_player_elo_non_negative"
    )


def test_player_names_are_unique_ignoring_case(seeded: Engine) -> None:
    assert violated(seeded, "INSERT INTO player (name, elo) VALUES ('a', 1000)") == (
        "uq_player_name_lower"
    )


def test_best_of_must_be_odd(seeded: Engine) -> None:
    sql = (
        "INSERT INTO tournament (name, status, best_of, default_elo_delta)"
        " VALUES ('X', 'draft', 2, 25)"
    )
    assert violated(seeded, sql) == "ck_tournament_best_of_positive_odd"


def test_match_players_must_be_entrants_of_that_tournament(seeded: Engine) -> None:
    # Composite FK (tournament_id, player_id) -> tournament_entrant.
    assert violated(seeded, match_sql(1, "3")) == (
        "fk_match_tournament_id_player_two_id_tournament_entrant"
    )


def test_bye_iff_no_second_player(seeded: Engine) -> None:
    assert violated(seeded, match_sql(1, "NULL")) == "ck_match_bye_has_one_player"
    assert violated(seeded, match_sql(1, "2", outcome="bye", winner="1")) == (
        "ck_match_bye_has_one_player"
    )


def test_winner_must_be_one_of_the_players(seeded: Engine) -> None:
    assert violated(seeded, match_sql(1, "2", outcome="played", winner="3")) == (
        "ck_match_winner_is_a_player"
    )


def test_pending_match_cannot_have_a_winner(seeded: Engine) -> None:
    assert violated(seeded, match_sql(1, "2", winner="1")) == "ck_match_pending_has_no_winner"


def test_ledger_rows_must_add_up(seeded: Engine) -> None:
    insert(seeded, match_sql(1, "2", outcome="played", winner="1"))
    sql = (
        "INSERT INTO elo_change (player_id, match_id, reason, elo_before, elo_after, delta)"
        " VALUES (1, 1, 'match', 1000, 1025, 30)"
    )
    assert violated(seeded, sql) == "ck_elo_change_delta_matches_before_after"


def test_player_with_history_cannot_be_deleted(seeded: Engine) -> None:
    assert violated(seeded, "DELETE FROM player WHERE id = 1") == (
        "fk_tournament_entrant_player_id_player"
    )


def test_head_to_head_view_counts_played_matches(seeded: Engine) -> None:
    insert(seeded, match_sql(2, "1", outcome="played", winner="2"))
    insert(seeded, match_sql(1, "2", outcome="played", winner="2"))
    insert(seeded, match_sql(1, "2"))  # pending: not counted

    with seeded.connect() as conn:
        row = conn.execute(text("SELECT * FROM head_to_head")).one()

    assert row._asdict() == {
        "player_a_id": 1,
        "player_b_id": 2,
        "wins_a": 0,
        "wins_b": 2,
        "matches": 2,
    }
