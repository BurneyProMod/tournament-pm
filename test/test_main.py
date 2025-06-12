import pytest
from pathlib import Path
import sqlite3

import main

@pytest.fixture
def db_conn(tmp_path):
    conn = main.init_db(Path(":memory:"))
    yield conn
    conn.close()

def test_init_db_creates_all_tables(db_conn):
    cur = db_conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    names = {row[0] for row in cur.fetchall()}
    assert {"player", "head_to_head", "tournament", "match"}.issubset(names)

# Create a test player in the database and return the ID
def create_test_player(conn, name, elo):
    cur = conn.cursor()
    cur.execute("INSERT INTO player (name, elo) VALUES (?, ?)", (name, elo))
    conn.commit()
    return cur.lastrowid

# Return player's current ELO
def get_player_elo(conn, player_id):
    cur = conn.cursor()
    cur.execute("SELECT elo FROM player WHERE id=?", (player_id,))
    return cur.fetchone()[0]

# Return player's head-to-head record against another player
def get_head_to_head_record(conn, p1_id, p2_id):
    cur = conn.cursor()
    a, b = sorted((p1_id, p2_id))
    cur.execute("""
        SELECT wins_a, wins_b FROM head_to_head
        WHERE player_a_id=? AND player_b_id=?
    """, (a, b))
    result = cur.fetchone()
    if result is None:
        return (0, 0)
    wins_a, wins_b = result
    return (wins_a, wins_b) if a == p1_id else (wins_b, wins_a)

def test_load_players_from_file(tmp_path):
    # Create csv with 4 entries
    users = tmp_path / "test_users.txt"
    users.write_text(
        "Alice,1200\n"
        "Bob,1100\n"
        "Charlie,500\n"
        "David,1500\n"
    )
    # Init a test database
    db_file = tmp_path / "db.sqlite"
    conn = main.init_db(db_file)

    # Call the loader function
    main.seed_players(conn, path=str(users))  # This function should probably be renamed too
    
    # Assert rows in player table (ordered by name)
    cur = conn.cursor()
    cur.execute("SELECT name, elo FROM player ORDER BY name")
    assert cur.fetchall() == [
        ("Alice",   1200),
        ("Bob",     1100),
        ("Charlie",  500),
        ("David",   1500),
    ]

def test_load_players_handles_empty_file(tmp_path):
    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("")
    
    db_file = tmp_path / "test.db"
    conn = main.init_db(db_file)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM player")
    assert cur.fetchone()[0] == 0

def test_apply_delta_updates_elo_and_head_to_head(db_conn):
    # Set up test data
    cur = db_conn.cursor()
    cur.execute("INSERT INTO player (name, elo) VALUES ('Player1', 1000)")
    p1_id = cur.lastrowid
    cur.execute("INSERT INTO player (name, elo) VALUES ('Player2', 1000)")
    p2_id = cur.lastrowid
    db_conn.commit()

    # Perform the operation
    main.apply_delta(db_conn, p1_id, p2_id, delta=50)

    # Verify results
    cur.execute("SELECT elo FROM player WHERE id=?", (p1_id,))
    assert cur.fetchone()[0] == 1050, "Winner should gain 50 ELO"
    
    cur.execute("SELECT elo FROM player WHERE id=?", (p2_id,))
    assert cur.fetchone()[0] == 950, "Loser should lose 50 ELO"

    # Check head-to-head record
    player_a_id, player_b_id = sorted((p1_id, p2_id))
    cur.execute("""
        SELECT wins_a, wins_b FROM head_to_head
        WHERE player_a_id=? AND player_b_id=?
    """, (player_a_id, player_b_id))
    
    wins_a, wins_b = cur.fetchone()
    if player_a_id == p1_id:
        assert (wins_a, wins_b) == (1, 0), "Player A should have 1 win, 0 losses"
    else:
        assert (wins_a, wins_b) == (0, 1), "Player B should have 1 win, 0 losses"

def test_apply_delta_prevents_negative_elo(db_conn):
    """Test that ELO doesn't go below 0"""
    cur = db_conn.cursor()
    
    # Create a low-ELO player
    cur.execute("INSERT INTO player (name, elo) VALUES ('Beginner', 25)")
    low_elo_id = cur.lastrowid
    cur.execute("INSERT INTO player (name, elo) VALUES ('Expert', 1500)")
    high_elo_id = cur.lastrowid
    db_conn.commit()
    
    # Expert beats beginner with large delta
    main.apply_delta(db_conn, high_elo_id, low_elo_id, delta=50)
    
    cur.execute("SELECT elo FROM player WHERE id=?", (low_elo_id,))
    final_elo = cur.fetchone()[0]
    assert final_elo >= 0, "ELO should never go below 0"

# Test seeding with an empty file
def test_seed_players_handles_empty_file(tmp_path):
    empty_file = tmp_path / "empty.txt"
    empty_file.write_text("")
    
    db_file = tmp_path / "test.db"
    conn = main.init_db(db_file)
    
    # Should not crash on empty file
    main.seed_players(conn, path=str(empty_file))
    
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM player")
    assert cur.fetchone()[0] == 0

# Test seeding with even amount of players
def test_create_first_tournament_with_even_players(db_conn):
    cur = db_conn.cursor()
    cur.executemany(
        "INSERT INTO player(name,elo) VALUES(?,?)",
        [("Player1", 400), ("Player2", 300), ("Player3", 200), ("Player4", 100)]
    )
    db_conn.commit()
    
    ids = [row[0] for row in cur.execute("SELECT id FROM player ORDER BY elo DESC")]
    matches = main.create_first_tournament(db_conn, ids, default_delta=10)
    
    # Should have 2 matches, no byes
    real_matches = [m for m in matches if m[4] is not None]  # m[4] is opponent
    bye_matches = [m for m in matches if m[4] is None]
    
    assert len(real_matches) == 2, "Should have exactly 2 matches"
    assert len(bye_matches) == 0, "Should have no bye matches"

def test_create_first_tournament_pairs_correctly(db_conn):
    cur = db_conn.cursor()
    cur.executemany(
        "INSERT INTO player(name,elo) VALUES(?,?)",
        [("A", 300), ("B", 200), ("C", 100)]
    )
    db_conn.commit()
    ids = [row[0] for row in cur.execute("SELECT id FROM player ORDER BY elo DESC")]

    matches = main.create_first_tournament(db_conn, ids, default_delta=10)
    # Expect one bye (middle Elo=200) and one real match between 300 vs 100
    assert any(m[1] == "A" and m[4] == "C" for m in matches)
    assert any(m[1] == "B" and m[4] is None for m in matches)