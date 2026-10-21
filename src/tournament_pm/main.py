from fastapi import FastAPI

from tournament_pm.api.errors import install_error_handlers
from tournament_pm.api.routes import matches, players, tournaments
from tournament_pm.db.session import SessionFactory, make_session_factory


def create_app(session_factory: SessionFactory | None = None) -> FastAPI:
    app = FastAPI(
        title="Tournament PM",
        version="0.1.0",
        description="Swiss-style tournaments with Elo ratings.",
    )
    # The engine connects lazily, so building the app never needs a live database.
    app.state.session_factory = session_factory or make_session_factory()
    install_error_handlers(app)
    for router in (players.router, tournaments.router, matches.router):
        app.include_router(router)

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
