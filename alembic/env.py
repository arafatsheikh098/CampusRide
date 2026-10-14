"""Alembic environment. Uses the same DATABASE_URL the app reads from env."""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import metadata for autogenerate / offline SQL.
from app import models  # noqa: F401  registers every model
from app.config import get_settings
from sqlmodel import SQLModel

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
# Prefer the URL set in the alembic Config (so tests and the CLI can pass a
# different database than the app's default). Fall back to app settings.
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=url.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    # Honor the URL already set on the config (tests, CLI override).
    if not section.get("sqlalchemy.url"):
        section["sqlalchemy.url"] = settings.database_url
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        is_sqlite = connection.dialect.name == "sqlite"
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=is_sqlite,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()