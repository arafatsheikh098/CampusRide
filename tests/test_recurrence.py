"""Recurrence generator (F4). Pure stdlib module, no web/db imports."""
from __future__ import annotations

import inspect
from datetime import date, datetime, time, timezone

from app import recurrence
from app.recurrence import (
    DHAKA,
    generate_weekly,
    generate_series,
    iter_weekly_dates,
    to_utc,
    window_minutes,
)


def test_recurrence_module_has_no_web_or_db_imports():
    """Generator must be pure. SQLAlchemy / FastAPI / sqlmodel must not leak in."""
    src = inspect.getsource(recurrence)
    assert "fastapi" not in src
    assert "sqlmodel" not in src
    assert "sqlalchemy" not in src
    assert "app.db" not in src
    assert "app.routes" not in src


def test_to_utc_converts_dhaka_to_utc():
    local = datetime(2026, 3, 1, 8, 0, tzinfo=DHAKA)  # 02:00 UTC
    utc = to_utc(local)
    assert utc.tzinfo is timezone.utc
    assert utc.hour == 2


def test_window_minutes_basic():
    a = datetime(2026, 3, 1, 8, 0, tzinfo=DHAKA)
    b = datetime(2026, 3, 1, 8, 30, tzinfo=DHAKA)
    assert window_minutes(a, b) == 30


def test_window_minutes_reversed_is_negative():
    a = datetime(2026, 3, 1, 8, 0, tzinfo=DHAKA)
    b = datetime(2026, 3, 1, 7, 0, tzinfo=DHAKA)
    assert window_minutes(a, b) == -1


def test_iter_weekly_dates_mon_wed_fri():
    start = date(2026, 3, 2)  # Monday
    end = date(2026, 3, 8)    # Sunday
    mask = (1 << 0) | (1 << 2) | (1 << 4)  # Mon Wed Fri
    out = list(iter_weekly_dates(start, end, mask))
    assert [d.weekday() for d in out] == [0, 2, 4]
    assert [d.isoformat() for d in out] == ["2026-03-02", "2026-03-04", "2026-03-06"]


def test_generate_weekly_within_horizon():
    start = date(2026, 3, 2)
    end = date(2026, 3, 22)
    mask = (1 << 0)  # Monday only
    out = generate_weekly(start, end, mask, time(8, 0))
    assert len(out) == 3
    assert all(d.tzinfo == DHAKA for d in out)
    # Three Mondays: Mar 2, 9, 16
    assert [d.date().isoformat() for d in out] == ["2026-03-02", "2026-03-09", "2026-03-16"]


def test_generate_series_caps_at_horizon():
    start = date(2026, 3, 2)
    end = date(2026, 3, 30)
    mask = (1 << 0) | (1 << 1)  # Mon + Tue
    earliest = datetime(2026, 3, 2, 8, 0, tzinfo=DHAKA)
    horizon_end = datetime(2026, 3, 10, 23, 59, tzinfo=DHAKA)
    out = generate_series(
        recurrence_kind="weekly",
        series_start_local=start,
        series_end_local=end,
        weekdays_mask=mask,
        earliest_local=earliest,
        horizon_end_local=horizon_end,
    )
    # Within horizon: Mon 2, Tue 3, Mon 9, Tue 10.
    assert [d.date().isoformat() for d in out] == [
        "2026-03-02", "2026-03-03", "2026-03-09", "2026-03-10",
    ]
    # All UTC, sorted.
    assert all(d.tzinfo is timezone.utc for d in out)
    assert out == sorted(out)


def test_generate_series_one_off_returns_one():
    earliest = datetime(2026, 3, 5, 8, 0, tzinfo=DHAKA)
    horizon = datetime(2026, 3, 5, 23, 59, tzinfo=DHAKA)
    out = generate_series(
        recurrence_kind="one_off",
        series_start_local=earliest.date(),
        series_end_local=None,
        weekdays_mask=0,
        earliest_local=earliest,
        horizon_end_local=horizon,
    )
    assert len(out) == 1
    assert out[0].astimezone(DHAKA) == earliest
