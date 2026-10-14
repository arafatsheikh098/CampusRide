"""Pytest configuration: build a TestClient with a fresh SQLite file."""
from __future__ import annotations


import pytest
from fastapi.testclient import TestClient
from sqlalchemy import StaticPool, create_engine
from sqlmodel import Session, SQLModel

# Import the models so SQLModel.metadata has every table.
from app import models  # noqa: F401
from app.config import Settings
from app.db import set_engine
from app.main import create_app


@pytest.fixture()
def settings() -> Settings:
    return Settings(
        app_env="development",
        secret_key="test-secret-key-32-characters-long-yes",
        database_url="sqlite:///:memory:",
        default_lang="en",
        supported_langs="en,bn",
        campus_name="Test Campus",
        campus_timezone="Asia/Dhaka",
        emergency_number="999",
        member_cap=200,
        retention_days=90,
        trip_horizon_days=14,
        last_minute_window_minutes=120,
        time_match_tolerance_minutes=15,
        cost_per_seat_cap_paisa=50000,
        run_worker_in_process=False,
        heartbeat_interval_seconds=30,
        women_only_trips=False,
        demo_mode=False,
    )


@pytest.fixture()
def engine(settings):
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    set_engine(eng)
    SQLModel.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def client(settings, engine) -> TestClient:
    app = create_app(settings)
    return TestClient(app)


@pytest.fixture()
def db_session(engine) -> Session:
    with Session(engine) as s:
        yield s
