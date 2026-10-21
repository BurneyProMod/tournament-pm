# Tournament PM

![CI](https://github.com/BurneyProMod/tournament-pm/actions/workflows/ci.yml/badge.svg)

A REST API for running Swiss-style tournaments with Elo ratings. A match admin registers players, creates a tournament, generates pairings round by round, reports best-of-N results, and gets final standings, with every Elo change recorded.

**Stack:** Python 3.13 · FastAPI · PostgreSQL · SQLAlchemy 2 · Alembic · pytest · Docker · GitHub Actions

> Status: MVP. The full tournament workflow runs through the REST API and is covered by an automated end-to-end test. See [ROADMAP.md](ROADMAP.md) for design notes and what's next.

## Run it

```bash
docker compose up --build
```

The API is served at http://localhost:8000. Interactive docs are at http://localhost:8000/docs.

## API

| Method | Path | What it does |
|---|---|---|
| `POST` | `/players` | Register a player (name, starting Elo) |
| `GET` | `/players`, `/players/{id}` | List or fetch players |
| `DELETE` | `/players/{id}` | Archive a player (history is kept) |
| `POST` | `/tournaments` | Create a tournament (best-of-N, Elo delta) |
| `POST` | `/tournaments/{id}/entrants` | Enter a player |
| `POST` | `/tournaments/{id}/start` | Seed by Elo and pair round 1 |
| `PUT` | `/matches/{id}/result` | Report game winners; applies Elo in one transaction |
| `DELETE` | `/matches/{id}/result?version=N` | Undo a result while its round is open |
| `POST` | `/tournaments/{id}/rounds` | Close the current round and Swiss-pair the next |
| `GET` | `/tournaments/{id}/rounds/{n}` | A round's matches |
| `GET` | `/tournaments/{id}/standings` | Points → Buchholz → head-to-head → Elo |

Errors always look like `{"error": {"code": "STALE_VERSION", "message": "...", "details": {...}}}`:
404 for unknown resources, 409 when the request conflicts with current state (duplicate name,
round not finished, outdated `version`), and 422 when the input breaks a rule.

[`tests/integration/test_api.py`](tests/integration/test_api.py) has a full 7-player, 3-round tournament played through the API.

## Develop

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
docker compose up -d db      # Postgres for the integration tests
```

| Task | Command |
|---|---|
| Run the API with reload | `uvicorn tournament_pm.main:app --reload` |
| Tests + coverage | `pytest` (unit tests need nothing; integration tests use the `db` container and create a `tournament_test` database) |
| Apply migrations | `alembic upgrade head` |
| New migration | `alembic revision --autogenerate -m "..."`, then review it |
| Lint / format | `ruff check .` · `ruff format .` |
| Type check | `mypy` |

CI runs the same checks on every push and pull request.

## Project layout

```
src/tournament_pm/
  domain/            pure rules: Elo, best-of-N validation, Swiss pairing, standings
  db/                SQLAlchemy models (constraints included) and session setup
  services/          use cases, each one database transaction
  main.py            FastAPI app
migrations/          Alembic migrations
tests/
  unit/              domain tests, including Hypothesis property tests
  integration/       schema, service and concurrency tests against real Postgres
legacy/              original SQLite prototype (reference only)
ROADMAP.md           audit, design (data model, REST surface), phased plan
```

## Requirements

These come from the original project brief.

**Admin workflow**
1. **Create a tournament:** name it, add or remove players (name and Elo), set games per match (best of 1, 3, 5, …), review round 1 seeding (high/low), edit pairings and the default Elo gain/loss.
2. **Run rounds:** for each match, optionally adjust its Elo gain/loss, record the winner and submit. When every match in a round is done, generate the next round.
3. **Show results:** the final standings, with the ± Elo after each match.

**Rules**
- Basic Elo with an adjustable gain/loss; Elo can't go below 0.
- Player names and Elo are saved between tournaments; names are sanitized.
- The number of games per match is configurable.
- Only the match admin uses the system; players don't need access.
