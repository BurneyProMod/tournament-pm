"""One place that turns errors into HTTP responses, all with the same body shape:
{"error": {"code": "...", "message": "...", "details": {...}}}
"""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from tournament_pm.api.schemas import ErrorResponse
from tournament_pm.domain.errors import (
    ConflictError,
    DomainError,
    NotEnoughPlayersError,
    NotFoundError,
)


def status_for(error: DomainError) -> int:
    if isinstance(error, NotFoundError):
        return status.HTTP_404_NOT_FOUND
    if isinstance(error, ConflictError | NotEnoughPlayersError):
        return status.HTTP_409_CONFLICT  # valid request, wrong moment
    return status.HTTP_422_UNPROCESSABLE_CONTENT  # request breaks a rule


def _error(status_code: int, code: str, message: str, details: dict[str, Any]) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": jsonable_encoder(details)}},
    )


async def _domain_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    return _error(status_for(exc), exc.code, exc.message, exc.details)


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = [
        {"field": ".".join(str(part) for part in e["loc"]), "message": e["msg"]}
        for e in exc.errors()
    ]
    return _error(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "VALIDATION_ERROR",
        "Request is invalid",
        {"errors": errors},
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(DomainError, _domain_error)
    app.add_exception_handler(RequestValidationError, _validation_error)


# For OpenAPI docs: routes list these so /docs shows the error shape.
ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    404: {"model": ErrorResponse, "description": "Not found"},
    409: {"model": ErrorResponse, "description": "Conflicts with current state"},
    422: {"model": ErrorResponse, "description": "Invalid request"},
}
