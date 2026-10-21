from datetime import UTC, datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tournament_pm.domain.errors import NotFoundError


def now() -> datetime:
    return datetime.now(UTC)


def get_or_404[T](
    session: Session, model: type[T], ident: Any, *, lock: bool | dict[str, bool] = False
) -> T:
    """Load a row by primary key, optionally locking it (`SELECT ... FOR UPDATE`)."""
    row = session.get(model, ident, with_for_update=lock or None)
    if row is None:
        raise NotFoundError(f"{model.__name__} not found", id=ident)
    return row


def violated_constraint(exc: IntegrityError) -> str | None:
    """Name of the Postgres constraint behind an IntegrityError (via psycopg's diagnostics)."""
    diag = getattr(exc.orig, "diag", None)
    return getattr(diag, "constraint_name", None)
