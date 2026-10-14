"""Security baseline: SECRET_KEY default refusal (M2 A7 — confirmed already in M1)."""
from __future__ import annotations

import pytest

from app.config import Settings, get_settings
from app.security import DEFAULT_SECRET


def _with_settings(**overrides) -> Settings:
    """Build a Settings, bypassing the cache so each test is isolated."""
    s = Settings(**overrides)
    get_settings.cache_clear()
    # Override the cached factory for the duration of the test.
    import app.config as cfg

    cfg.get_settings = lambda: s  # type: ignore[assignment]
    return s


def test_production_refuses_default_secret_key() -> None:
    _with_settings(app_env="production", secret_key=DEFAULT_SECRET, database_url="sqlite:///:memory:")
    from app.security import assert_safe_secret_key as fn
    with pytest.raises(RuntimeError):
        fn()


def test_production_refuses_short_secret_key() -> None:
    _with_settings(app_env="production", secret_key="short", database_url="sqlite:///:memory:")
    from app.security import assert_safe_secret_key as fn
    with pytest.raises(RuntimeError):
        fn()


def test_development_does_not_refuse_default() -> None:
    _with_settings(app_env="development", secret_key=DEFAULT_SECRET, database_url="sqlite:///:memory:")
    from app.security import assert_safe_secret_key as fn
    fn()  # should not raise