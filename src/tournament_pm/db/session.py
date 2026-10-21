import os

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DATABASE_URL = "postgresql+psycopg://tournament:tournament@localhost:5432/tournament"

SessionFactory = sessionmaker[Session]


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL)


def make_session_factory(url: str | None = None) -> SessionFactory:
    engine = create_engine(url or database_url(), pool_pre_ping=True)
    # expire_on_commit=False: services return ORM rows that stay readable after commit.
    return sessionmaker(engine, expire_on_commit=False)
