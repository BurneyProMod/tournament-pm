# Tournament PM — Status Audit & Demo Roadmap

_Audited 2026-10-17 against `main` @ `5b95156`._

## 1. Current status

The project is at the **data-layer prototype** stage. None of the user-facing workflow in the README exists yet.

| Area | File | State |
|---|---|---|
| SQLite schema (player, head_to_head, tournament, match) | `main.py` | ✅ Written, reasonable shape |
| Apply win/loss Elo delta + head-to-head | `main.py` `apply_delta` | ✅ Works (flat ±delta) |
| Bulk player import from CSV | `main.py` `seed_players` | ⚠️ Reads `test_users.txt`, which doesn't exist |
| Simulated tournament | `generateTestTournament.py` | ⚠️ Runs, but it's **single elimination**, not Swiss |
| Player management | `players.py` | ❌ Empty file |
| Seeding / round pairing | `tournament.py` | ❌ Only a TODO comment |
| Admin UI (create, enter results, view bracket) | — | ❌ Not started |
| Tests, dependencies, run instructions | — | ❌ None |

### Issues found

1. **The committed DB doesn't match the code.** `tournament.db`'s `player` table has no `matches_played` or `tournaments_attended` columns. `CREATE TABLE IF NOT EXISTS` won't add them, so any code that uses those columns will fail on the existing file.
2. **Generated files are in git.** `tournament.db` and `tournament.log` were committed before `.gitignore` was added, so git still tracks them. The DB holds 127 leftover `SimPlayer_*` rows, and their Elo has been changed by past simulations.
3. **The simulator leaves data behind.** It deletes its tournament row (and its matches, through the foreign-key cascade) but keeps the players, the head-to-head records and the Elo changes. Running it repeatedly fills the real player pool with test players.
4. **`apply_delta` commits on its own.** Recording a match result can't be wrapped in a larger transaction (write the result, update Elo, move the round forward) or rolled back.
5. **Two README TODOs are still open:** Elo can go below 0, and player names aren't sanitized.
6. **`games_per_match` is stored but never used.** No code records or checks best-of-N game scores (`score_p1`/`score_p2`).
7. **The `random_name()` retry loop doesn't retry.** It runs once, so a duplicate name raises `IntegrityError` instead of generating a new name.
8. **There's no code layout.** Logic sits at module top level, and `main.py` is really `db.py`. That makes it hard to reuse from a UI or from tests.

## 2. Project goal

_Updated 2026-10-17._ This is a **portfolio project** to support a move from Enterprise Applications Engineer into software development. Each phase is ordered by what it shows a reviewer, not by how quickly it gets something on screen. These are the skills it needs to show, and where the evidence will be:

| Skill to show | Where a reviewer will see it |
|---|---|
| Python backend development | A layered FastAPI service (`api/` → `services/` → `domain/` + `db/`), type hints throughout, linted with `ruff` and type-checked with `mypy` |
| REST endpoints | Resource-oriented routes, correct status codes (201/204/404/409/422), consistent error bodies, auto-generated OpenAPI docs at `/docs` |
| Relational data modeling | A normalized schema with FKs, CHECK/UNIQUE constraints and an Elo **ledger** table; an ERD in the README; Alembic migrations |
| Transactions | Reporting a result writes the result, the Elo changes and the round state atomically, with row locking so double-submits are blocked; undo is also atomic |
| Input validation | Pydantic request models, and domain rules (best-of-N score is valid, players are in this tournament, round is open) mapped to 422 or 409 |
| Automated tests | Unit tests for pairing and Elo logic, property-based pairing tests (`hypothesis`), API integration tests against real Postgres, coverage report, GitHub Actions CI badge |

**What this changes from the earlier plan:** the backend becomes the product, and any UI is a client of it. The earlier Flet design (UI talking straight to SQLite, no server) had **no REST layer at all**, so it would have hidden two of the six skills. Android stays possible: a Flet or other mobile client calls the same API later.

## 3. Demo definition

A reviewer should be able to do all of this in about 5 minutes, without talking to you:

1. Open the repo and see a CI badge, a coverage percentage, an ERD and a "how to run" section with a single command (`docker compose up`).
2. Open `/docs` on the hosted demo or locally and run the whole tournament flow from Swagger UI: create players → create tournament → add entrants → generate round 1 → report results → generate round 2 → standings.
3. Run `scripts/simulate.py` and watch a full Swiss event (7 or 8 players) play out through the API.
4. Read 2–3 short design notes (ADRs) on decisions such as "why an Elo ledger" and "how double-submits are prevented".

**Out of scope for the first demo:** a graphical UI, auth, multi-tenant support and double elimination. A thin UI is Phase 4, after the backend is solid.

## 4. Recommended stack

| Concern | Choice | Why it reads well on a resume |
|---|---|---|
| Web framework | **FastAPI** | Widely used, validation through Pydantic, free OpenAPI docs |
| DB | **PostgreSQL 16** (Docker) | What employers run; real row locking (`SELECT … FOR UPDATE`) to show transaction handling. SQLite can't show this convincingly. |
| DB access | **SQLAlchemy 2.0** with explicit `session.begin()` blocks | Industry standard; transaction boundaries stay visible in the code |
| Migrations | **Alembic** | Shows schema change done properly; also fixes issue #1 above |
| Tests | **pytest**, **hypothesis**, **httpx** TestClient, Postgres in CI as a service container | Shows a real test pyramid rather than just unit tests |
| Quality | `ruff`, `mypy`, `pre-commit`, GitHub Actions | Reviewers look for these |
| Packaging | `pyproject.toml` (uv or pip), `Dockerfile`, `docker-compose.yml` | One-command run |

### Layout

```
src/tournament_pm/
  domain/        # pure logic, no I/O: elo.py, pairing.py, standings.py, errors.py
  db/            # SQLAlchemy models, session, Alembic env
  services/      # use cases; each one is a single transaction (report_result, generate_round, …)
  api/           # FastAPI routers + Pydantic schemas; maps domain errors to HTTP
  main.py        # app factory
migrations/
tests/
  unit/          # domain/, no DB
  integration/   # services + API against Postgres
scripts/simulate.py
docs/adr/
```

### Data model (agreed 2026-10-17)

```
player ──< tournament_entrant >── tournament ──< round ──< match ──< game
   │                                                         │
   └──────────────────< elo_change >─────────────────────────┘
```

```
player(id, name, elo CHECK >= 0, archived_at NULL, created_at)
    UNIQUE (lower(name))
tournament(id, name, status CHECK IN (draft, active, complete),
           best_of CHECK (best_of > 0 AND best_of % 2 = 1),
           default_elo_delta CHECK >= 0, seeding_method DEFAULT 'top_half_vs_bottom_half',
           rounds_planned, created_at)
tournament_entrant(tournament_id, player_id, seed, elo_at_entry, dropped_at NULL,
                   PK (tournament_id, player_id))
round(id, tournament_id, number, status CHECK IN (pending, open, closed),
      UNIQUE (tournament_id, number))
match(id, round_id, player_one_id, player_two_id NULL,
      outcome CHECK IN (pending, played, forfeit, bye),
      winner_id NULL, elo_delta CHECK >= 0, reported_at NULL, version DEFAULT 0)
      CHECK (player_one_id <> player_two_id)
      CHECK (winner_id IN (player_one_id, player_two_id))
      CHECK ((outcome = 'bye') = (player_two_id IS NULL))
      -- "one match per player per round" spans two columns, so a plain UNIQUE can't express it;
      -- enforced in generate_round + a property test (a match_slot table is the DB-level option)
game(match_id, game_number, winner_id, PK (match_id, game_number))
elo_change(id, match_id, player_id, elo_before, elo_after, delta, reason, created_at)
      -- append-only ledger; reason IN (match, undo, manual_adjustment)
head_to_head → SQL VIEW over match WHERE outcome = 'played'
```

All FKs to `player` use **`ON DELETE RESTRICT`**: once a player has history they can only be archived.

**Rules agreed in the walkthrough:**

| Situation | Behavior |
|---|---|
| Round 1 seeding | Sort by `elo_at_entry`, then **top half vs bottom half** (1 vs N/2+1, 2 vs N/2+2, …). `seeding_method` is stored so 1-vs-N can be added later |
| Match result | Recorded **per game** in `game`; the service checks that the winner reached `ceil(best_of/2)` wins and that no games were recorded after that |
| Elo timing | Applied **when each result is reported**: the match row, the game rows, the `elo_change` rows and the `player.elo` update go in one transaction |
| BYE | `outcome = bye`, counts as a match win, **Elo change 0** |
| Player drops | `dropped_at` is set. Any open match they have, and **every match they are paired into later**, is recorded as `outcome = forfeit` with the opponent as winner, no game rows and **Elo change 0**. They stay in the pairing pool (for now) |
| Undo | Allowed while the round is `open`; writes reversing `elo_change` rows (`reason = undo`) and deletes the `game` rows, then sets the match back to `pending` |
| Delete player | Archives them (`archived_at`). Archived players are hidden from lists and can't be entered into new tournaments |

The ledger turns undo into "add reversing ledger rows" and gives the per-match ±Elo on the results screen for free. It's a good design point to talk through in interviews.

### REST surface (agreed 2026-10-17)

| Method & path | Purpose | Main error codes |
|---|---|---|
| `POST /players` | Create a player | 409 duplicate name, 422 |
| `GET /players?search=&include_archived=` | List players | |
| `GET /players/{id}` | Get one player | 404 |
| `PATCH /players/{id}` | Rename, or correct Elo by hand (written to the ledger as `manual_adjustment`) | 404, 409, 422 |
| `DELETE /players/{id}` | Archive (soft delete) | 404 |
| `GET /players/{id}/history` | Elo ledger | 404 |
| `POST /tournaments` | Create (status `draft`) | 422 |
| `GET /tournaments?status=` | List tournaments | |
| `GET /tournaments/{id}` | Details, entrants and rounds | 404 |
| `PATCH /tournaments/{id}` | Change name, best-of or delta (draft only) | 409 not draft |
| `POST /tournaments/{id}/entrants` | Add a player | 409 already entered / not draft / archived |
| `DELETE /tournaments/{id}/entrants/{pid}` | Remove a player (draft only) | 404, 409 |
| `POST /tournaments/{id}/entrants/{pid}/drop` | Drop a player (active); forfeits their open match | 404, 409 |
| `POST /tournaments/{id}/start` | `draft → active`: fixes seeds and `elo_at_entry`, sets `rounds_planned` | 409 if fewer than 2 entrants |
| `POST /tournaments/{id}/rounds` | Generate the next round (status `pending`); matches with a dropped player are created as forfeits | 409 if a round is still open |
| `GET /tournaments/{id}/rounds/{n}` | A round and its matches | 404 |
| `POST /rounds/{id}/open` | `pending → open`, freezes the pairings | 409 |
| `PATCH /matches/{id}` | Swap a player or override the delta (pending round only) | 409, 422 |
| `PUT /matches/{id}/result` | Report the result: `{"games": [{"winner_id": 7}, …], "version": 3}`. Sending the same result again is safe | 409 stale version / round not open, 422 invalid game sequence |
| `DELETE /matches/{id}/result` | Undo a result | 409 if the round is closed, or the match is a BYE or forfeit |
| `POST /rounds/{id}/close` | Lock the round once every match has a result | 409 if matches are missing |
| `POST /tournaments/{id}/complete` | `active → complete` | 409 |
| `GET /tournaments/{id}/standings` | Standings: match points → Buchholz → head-to-head → Elo | 404 |

Lifecycle changes are `POST` action endpoints rather than `PATCH {status}`, because each change has its own rules. Every error uses the same body: `{"error": {"code": "ROUND_NOT_OPEN", "message": "…", "details": {…}}}`.

## 5. Roadmap

Effort is in focused working days. Each phase ends with a merged PR, so the git history also tells the story.

### Phase 0 — Foundation (1 day) ✅ done 2026-10-17, branch `phase-0-foundation`
- `git rm --cached tournament.db tournament.log`, and move the existing scripts to `legacy/` (or delete them once ported).
- Set up the `src/` layout, `pyproject.toml`, ruff, mypy, pre-commit, and a Docker Compose file running Postgres plus the app.
- Add a GitHub Actions workflow that runs lint, type checks and tests on every push, and put the badge in the README.
- From here on, work on branches and merge through PRs, even working alone. Reviewers read commit history.

### Phase 1 — Domain logic, test-first (2–3 days) ✅ done 2026-10-21, branch `tourny-logic`
- `elo.py`: flat delta (default 25, configurable), floor at 0, and a pluggable strategy so expected-score Elo can be added later.
- `pairing.py`: round-1 high/low seeding, then Swiss pairing (same-score groups, move unpaired players down a group, avoid rematches, fair BYE rule).
- `standings.py`: match points → Buchholz → head-to-head → Elo.
- Tests: example-based tests plus **hypothesis** property tests for 2–64 players (everyone paired exactly once, no rematches while one can be avoided, at most one BYE per player).

### Phase 2 — Schema, persistence and transactions (2–3 days) ✅ done 2026-10-21, branch `tourny-logic`

_Scope trimmed for the portfolio goal (2026-10-21): editing pairings, explicit round open/close endpoints and the drop endpoint are deferred. Rounds are `open`/`closed` only; generating the next round closes the current one. Dropped players' forfeits are created automatically when a round is generated._
- SQLAlchemy models plus the first Alembic migration for the schema above, with constraints in the DB, not only in Python.
- Services, each one transaction: `create_tournament`, `add_entrant`, `generate_round`, `report_result`, `undo_result`, `close_round`.
- `report_result` locks the match row (`FOR UPDATE`), checks its `version`, writes the ledger rows and updates `player.elo`, all or nothing.
- Integration tests: a rollback test (inject a failure partway through and confirm nothing changed) and a concurrency test (two simultaneous reports, one gets 409).

### Phase 3 — REST API and validation (2 days) ✅ MVP done 2026-10-21, branch `mvp`

_Done: player, tournament, entrant, start, round, result (report and undo) and standings endpoints; Pydantic request/response models; one error handler (404/409/422 with a stable `code`); OpenAPI docs list the error responses; an end-to-end API test plays a whole tournament. Deferred: rewriting `scripts/simulate.py` as an API client (the end-to-end test covers the smoke-test role)._
- Routers, Pydantic schemas (name sanitizing and length limits, odd `best_of`, valid game scores), and a single exception handler that maps domain errors to 404, 409 or 422 with a consistent error body.
- API tests covering the happy path and every error code for every endpoint.
- Rewrite `scripts/simulate.py` as an **API client**. It doubles as an end-to-end smoke test in CI.

### Phase 4 — Presentation (1–2 days)
- README: what it is, a GIF of the API or simulator, an ERD (Mermaid), the one-command run, the test and coverage commands, and links to the ADRs.
- 2–3 ADRs in `docs/adr/`.
- Deploy to a free tier (Render, Fly.io or Railway, with managed Postgres) so the demo is a clickable link.
- Optional: a minimal client (a Flet screen or a single HTML page) for the tournament workflow. It's nice to have, not something reviewers expect for a backend role.

**Total: about 8–11 working days.** Phases 0–3 cover all six skills; Phase 4 makes them easy to see.

### After the demo
- Mobile client (Flet → `flet build apk`) against the hosted API
- Auth for admins (OAuth2 password flow / JWT), audit log
- **Drop policy option:** re-pair the bracket using only active players instead of forfeiting matches against dropped ones. `dropped_at` and `outcome = forfeit` already support it, so no migration is needed
- Expected-score Elo, elimination formats, top-cut after Swiss
- Pagination and filtering on list endpoints, rate limiting, structured logging and metrics

## 6. Decisions

**Decided (2026-10-17):**
- **Interface:** API-first backend; any UI, mobile included, is a client of it.
- **Seeding:** round 1 pairs the top half against the bottom half (1 vs N/2+1).
- **Results:** recorded per game.
- **Elo:** a flat delta, applied after each match. BYE = win with Elo change 0.
- **Drops:** the dropped player's remaining matches are forfeit losses (Elo change 0). Re-pairing with only active players is a future option.
- **Deleting a player:** archives them (soft delete).
- **Existing DB data:** thrown away; Postgres starts with a fresh schema.

- **Forfeits:** Elo change 0 for both players. A forfeit win counts as a match win in the standings, and the dropped player still counts toward their opponents' Buchholz.
- **Elo floor:** the winner always gains the full delta, even when the loser is clamped at 0, so ratings aren't strictly zero-sum near 0.
- **BYE recipient:** the lowest-ranked player in the fairest tier. Active players without a BYE come first, then active players who already had one; dropped players only get one if no active player is left. Round 1 therefore gives it to the lowest seed.
- **BYE fairness vs. rematches:** the BYE tier rule wins. Rematches are avoided only among BYE choices from that tier.
- **Double forfeit** (two dropped players paired together): no winner, no points for either player.
- **Head-to-head tiebreak:** wins (played or forfeit) against the players still tied on points and Buchholz. A cycle leaves them tied, and then Elo decides.
- **Shared ranks:** players equal on every tiebreak share a rank (1, 1, 3).

**Still open:**
1. **Learning budget.** FastAPI, SQLAlchemy and Alembic are new tools. Is about 8–11 days realistic for your schedule, or should Phase 4's deployment wait?
