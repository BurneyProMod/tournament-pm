from typing import Annotated

from fastapi import Depends, Request

from tournament_pm.db.session import SessionFactory


def get_session_factory(request: Request) -> SessionFactory:
    factory: SessionFactory = request.app.state.session_factory
    return factory


Factory = Annotated[SessionFactory, Depends(get_session_factory)]
