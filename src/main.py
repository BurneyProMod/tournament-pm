#!/usr/bin/env python3

import sqlite3
import csv
from pathlib import Path

DB_PATH = Path("../data/tournament.db").resolve()

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS player (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    name                 TEXT    NOT NULL UNIQUE,
    elo                  INTEGER NOT NULL DEFAULT 1000,
    matches_played       INTEGER NOT NULL DEFAULT 0,
    tournaments_attended INTEGER NOT NULL DEFAULT 0,
    created_at           TEXT    NOT NULL DEFAULT (datetime('now'))
);


CREATE TABLE IF NOT EXISTS head_to_head (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_a_id INTEGER NOT NULL,
    player_b_id INTEGER NOT NULL,
    wins_a      INTEGER NOT NULL DEFAULT 0,
    wins_b      INTEGER NOT NULL DEFAULT 0,
    UNIQUE (player_a_id, player_b_id),
    FOREIGN KEY (player_a_id) REFERENCES player(id) ON DELETE CASCADE,
    FOREIGN KEY (player_b_id) REFERENCES player(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tournament (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT    NOT NULL,
    start_date      TEXT    NOT NULL DEFAULT (date('now')),
    rounds_total    INTEGER NOT NULL,
    games_per_match INTEGER NOT NULL DEFAULT 3
);

CREATE TABLE IF NOT EXISTS match (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    tournament_id   INTEGER NOT NULL,
    round_number    INTEGER NOT NULL,
    player_one_id   INTEGER NOT NULL,
    player_two_id   INTEGER,            -- nullable for BYEs
    winner_id       INTEGER,            -- NULL until result entered
    score_p1        INTEGER,
    score_p2        INTEGER,
    elo_delta       INTEGER NOT NULL DEFAULT 25,
    FOREIGN KEY (tournament_id) REFERENCES tournament(id) ON DELETE CASCADE,
    FOREIGN KEY (player_one_id)  REFERENCES player(id)     ON DELETE CASCADE,
    FOREIGN KEY (player_two_id)  REFERENCES player(id)     ON DELETE CASCADE,
    FOREIGN KEY (winner_id)      REFERENCES player(id)     ON DELETE SET NULL
);
"""

# Init databases
def init_db(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    with conn:
        conn.executescript(SCHEMA)
    return conn

# Update player ELO and Head to Head after match
def apply_delta(conn: sqlite3.Connection,
                winner_id: int,
                loser_id: int,
                delta: int = 25) -> None:
    cur = conn.cursor()

    # Update player ELO
    cur.execute(
        "UPDATE player SET elo = elo + ? WHERE id = ?",
        (delta, winner_id)
    )
    cur.execute(
        "UPDATE player SET elo = elo - ? WHERE id = ?",
        (delta, loser_id)
    )

    # Update head-to-head
    a, b = sorted((winner_id, loser_id))
    cur.execute(
        "SELECT id, wins_a, wins_b FROM head_to_head "
        "WHERE player_a_id = ? AND player_b_id = ?",
        (a, b)
    )
    row = cur.fetchone()
    if row is None:
        wins_a, wins_b = (1, 0) if a == winner_id else (0, 1)
        cur.execute(
            "INSERT INTO head_to_head "
            "(player_a_id, player_b_id, wins_a, wins_b) "
            "VALUES (?, ?, ?, ?)",
            (a, b, wins_a, wins_b)
        )
    else:
        h2h_id, wins_a, wins_b = row
        if a == winner_id:
            wins_a += 1
        else:
            wins_b += 1
        cur.execute(
            "UPDATE head_to_head SET wins_a = ?, wins_b = ? "
            "WHERE id = ?",
            (wins_a, wins_b, h2h_id)
        )
    conn.commit()

    with p.open(newline="", encoding="utf-8") as f, conn:
        reader = csv.reader(f)
        to_insert = []
        for row in reader:
            if not row or row[0].strip().startswith("#"):
                continue
            name = row[0].strip()
            try:
                elo = int(row[1].strip())
            except (IndexError, ValueError):
                continue
            to_insert.append((name, elo))

        conn.executemany(
            "INSERT OR IGNORE INTO player (name, elo) VALUES (?, ?)",
            to_insert
        )

if __name__ == "__main__":
    conn = init_db()
    seed_players(conn)
    print(f"Schema ready and players seeded (if `{Path('test_users.txt')}` existed).")
    conn.close()
