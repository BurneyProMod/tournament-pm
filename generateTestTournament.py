#!/usr/bin/env python3

import random, string, datetime, sqlite3, sys
from pathlib import Path

import main
from main import init_db, apply_delta

conn = init_db()
cur = conn.cursor()

# Test Tournament Variables
DELTA = 25
LOG_PATH = Path("tournament.log")

# Generate random name in pattern: SimPlayer_X99
def random_name() -> str:
    letters = ''.join(random.choices(string.ascii_uppercase, k=2))
    digits  = ''.join(random.choices(string.digits, k=2))
    return f"SimPlayer_{letters}{digits}"

# Insert n unique random players and return [(id,name,elo)]
def add_players(n: int):    
    players = []
    for _ in range(n):
        while True:
            name = random_name()
            elo = random.randint(500, 1500)
            cur.execute("INSERT INTO player (name, elo) VALUES (?,?)",
                        (name, elo))
            players.append((cur.lastrowid, name, elo))
            break
    conn.commit()
    return players



# User input
count = int(input("How many participants? ").strip())

# Generate tournament
players = add_players(count)
timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
title = f"Test Tournament {timestamp}"

cur.execute("""INSERT INTO tournament (title, rounds_total, games_per_match)
               VALUES (?,?,?)""", (title, 0, 1))
tid = cur.lastrowid

id_to_name = {pid: nm for pid, nm, _ in players}

# Simulate matches with coin flip until there is a winner
players.sort(key=lambda p: p[2], reverse=True)
active_ids = [pid for pid, _, _ in players]
round_no   = 1
match_no   = 1

log_lines = [f"# {title}  – {count} players"]

while len(active_ids) > 1:
    # If length is odd, median player gets a BYE
    bye_id = None
    if len(active_ids) % 2:
        mid = len(active_ids) // 2
        bye_id = active_ids.pop(mid)
        cur.execute("""INSERT INTO match
                       (tournament_id, round_number,
                        player_one_id, player_two_id,
                        winner_id, score_p1, score_p2, elo_delta)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (tid, round_no,
                     bye_id, None,
                     bye_id, 1, 0, 0))
        elo_now = cur.execute("SELECT elo FROM player WHERE id=?", (bye_id,)).fetchone()[0]
        log_lines.append(f"{match_no}, {id_to_name[bye_id]} ({elo_now})(+0) / BYE")
        match_no += 1

    # Pair Hi/Low
    next_round_ids = [bye_id] if bye_id else []

    ids = active_ids[:]
    while ids:
        hi = ids.pop(0)
        lo = ids.pop(-1)

        elo_hi = cur.execute("SELECT elo FROM player WHERE id=?", (hi,)).fetchone()[0]
        elo_lo = cur.execute("SELECT elo FROM player WHERE id=?", (lo,)).fetchone()[0]

        # Flip coin for winner
        winner_id, loser_id = (hi, lo) if random.choice([True, False]) else (lo, hi)

        # Write to log
        delta_hi = f"(+{DELTA})" if hi == winner_id else f"(-{DELTA})"
        delta_lo = f"(+{DELTA})" if lo == winner_id else f"(-{DELTA})"
        log_lines.append(
            f"{match_no}, {id_to_name[hi]} ({elo_hi}){delta_hi} / "
            f"{id_to_name[lo]} ({elo_lo}){delta_lo}"
        )
        cur.execute("""INSERT INTO match
                       (tournament_id, round_number,
                        player_one_id, player_two_id,
                        winner_id, score_p1, score_p2, elo_delta)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    (tid, round_no,
                     hi, lo,
                     winner_id, 1, 0, DELTA))

        apply_delta(conn, winner_id, loser_id, DELTA)
        next_round_ids.append(winner_id)
        match_no += 1

    conn.commit()
    active_ids = next_round_ids
    round_no  += 1

champion_id = active_ids[0]
champion_elo = cur.execute("SELECT elo FROM player WHERE id=?", (champion_id,)).fetchone()[0]
log_lines.append(f"# WINNER: {id_to_name[champion_id]}  (final Elo {champion_elo})")

# Write to Log
with LOG_PATH.open("a", encoding="utf-8") as fh:
    fh.write("\n".join(log_lines) + "\n\n")

cur.execute("DELETE FROM tournament WHERE id=?", (tid,))
conn.commit()
conn.close()

print(f"Tournament complete – champion is {id_to_name[champion_id]} – see {LOG_PATH}")
