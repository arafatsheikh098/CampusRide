"""Database engine and session factory.

We use SQLModel on top of SQLAlchemy 2.x. Engine is built once per process.
"""
from __future__ import annotations

from typing import Iterator

from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker as _sa_sessionmaker
from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings


def _build_engine() -> Engine:
    s = get_settings()
    url = s.database_url
    connect_args: dict = {}
    if url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(url, connect_args=connect_args, future=True, pool_pre_ping=True)


# `expire_on_commit=False` so SQLModel objects remain usable after the
# session commits and the session is closed. Tests create a User in one
# with-block and then read fields in another; this keeps that flow safe.
def make_session_factory(engine: Engine) -> _sa_sessionmaker:
    """Return a session factory that yields SQLModel Sessions with
    `expire_on_commit=False`. SQLModel's `Session` class adds the `.exec()`
    helper that the SQLAlchemy session doesn't provide."""
    return _sa_sessionmaker(engine, expire_on_commit=False, autoflush=False, class_=Session)


_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def set_engine(engine: Engine) -> None:
    """Override the engine (used by tests)."""
    global _engine
    _engine = engine


def get_session() -> Iterator[Session]:
    """FastAPI dependency: a SQLModel Session per request with
    `expire_on_commit=False` so attributes remain accessible after commit."""
    factory = make_session_factory(get_engine())
    with factory() as session:
        yield session


def init_db() -> None:
    """Create all tables. Used only in tests; production uses Alembic."""
    # Import models so they register on SQLModel.metadata.
    from . import models  # noqa: F401

    SQLModel.metadata.create_all(get_engine())
