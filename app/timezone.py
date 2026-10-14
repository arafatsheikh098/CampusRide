"""Time helpers. All datetimes stored in DB are UTC; display uses campus TZ."""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .config import Settings


def app_now(s: Settings) -> datetime:
    """Return the current wall-clock time in the campus timezone."""
    return datetime.now(tz=ZoneInfo(s.campus_timezone))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_local(dt: datetime, s: Settings) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ZoneInfo(s.campus_timezone))
