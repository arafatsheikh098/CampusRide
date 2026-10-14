"""Alembic upgrade/downgrade (M1 acceptance A2)."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlmodel import SQLModel

from app import models  # noqa: F401  registers all models


def _run_alembic(database_url: str) -> None:
    # Each invocation runs in-process so the test doesn't need a shell.
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", database_url)
    cfg.attributes["database_url"] = database_url
    command.upgrade(cfg, "head")


def _downgrade_alembic(database_url: str, revision: str = "base") -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", database_url)
    cfg.attributes["database_url"] = database_url
    command.downgrade(cfg, revision)


def test_alembic_upgrade_and_downgrade_on_sqlite(tmp_path: Path) -> None:
    db = tmp_path / "m.db"
    url = f"sqlite:///{db}"
    _run_alembic(url)
    eng = create_engine(url)
    try:
        names = set(inspect(eng).get_table_names())
        for expected in (
            "users",
            "places",
            "trips",
            "trip_instances",
            "bookings",
            "blocks",
            "reports",
            "notifications",
            "jobs",
            "heartbeats",
            "audit_log",
        ):
            assert expected in names
    finally:
        eng.dispose()
    # Downgrade to base; all our tables should be gone.
    _downgrade_alembic(url, "base")
    eng = create_engine(url)
    try:
        names = set(inspect(eng).get_table_names())
        # We only expect alembic's own bookkeeping table to remain.
        assert "users" not in names
        assert "trips" not in names
    finally:
        eng.dispose()


def test_sqlmodel_metadata_matches_alembic_tables(tmp_path: Path) -> None:
    """Every model in SQLModel.metadata has a corresponding Alembic table.

    This guards against future models added without a migration.
    """
    db = tmp_path / "m.db"
    url = f"sqlite:///{db}"
    _run_alembic(url)
    eng = create_engine(url)
    try:
        alembic_tables = set(inspect(eng).get_table_names())
    finally:
        eng.dispose()
    sqlmodel_tables = set(SQLModel.metadata.tables.keys())
    # Note: there may be a few extra alembic-only tables (alembic_version);
    # we only assert that every model has a backing table.
    missing = sqlmodel_tables - alembic_tables
    assert not missing, f"models without migration tables: {missing}"
