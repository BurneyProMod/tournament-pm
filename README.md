# Tournament PM

![CI](https://github.com/BurneyProMod/tournament-pm/actions/workflows/ci.yml/badge.svg)

A REST API for running Swiss-style tournaments with Elo ratings. A match admin registers players, creates a tournament, generates pairings round by round, reports best-of-N results, and gets final standings, with every Elo change recorded.

**Stack:** Python 3.13 · FastAPI · PostgreSQL · SQLAlchemy 2 · Alembic · pytest · Docker · GitHub Actions

> Status: Phase 0 (foundation) of [ROADMAP.md](ROADMAP.md). Domain logic, persistence and the full API are next.

## Run it

```bash
docker compose up --build
```

The API is served at http://localhost:8000. Interactive docs are at http://localhost:8000/docs.

## Develop

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
```

| Task | Command |
|---|---|
| Run the API with reload | `uvicorn tournament_pm.main:app --reload` |
| Tests + coverage | `pytest` |
| Lint / format | `ruff check .` · `ruff format .` |
| Type check | `mypy` |

CI runs the same checks on every push and pull request.

## Project layout

```
src/tournament_pm/   application package
tests/               pytest suite
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
