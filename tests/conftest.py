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
def settings(monkeypatch) -> Settings:
    s = Settings(
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
    import app.config as cfg

    # The lru_cache is per-process; only the original function has it.
    if hasattr(cfg.get_settings, "cache_clear"):
        cfg.get_settings.cache_clear()
    # Patch every module that did `from .config import get_settings` so the
    # test settings are visible throughout the app.
    import app.auth
    import app.main
    import app.security
    import app.routes.auth as ra
    import app.routes.moderation as rm
    import app.routes.profile as rp
    import app.routes.places as rpl
    import app.routes.driver as rd
    import app.routes.trips as rt
    import app.routes.search as rs
    import app.routes.bookings as rb
    import app.routes.trusted_contact as rtc
    import app.routes.blocks as rbl
    import app.routes.reports as rrp
    import app.routes.notifications as rn
    import app.routes.telegram as rtg
    import app.routes.policy as rpo
    import app.cli as cli_mod
    import app.worker as worker_mod
    for mod in (
        cfg, app.auth, app.main, app.security, ra, rm, rp, rpl, rd, rt, rs, rb, rtc, rbl, rrp, rn, rtg, rpo, cli_mod, worker_mod,
    ):
        monkeypatch.setattr(mod, "get_settings", lambda: s, raising=False)
    # app.security uses `_config.get_settings`; also patch `_config`.
    monkeypatch.setattr(app.security, "_config", cfg, raising=False)
    return s


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
    from app.db import make_session_factory
    factory = make_session_factory(engine)
    with factory() as s:
        yield s
