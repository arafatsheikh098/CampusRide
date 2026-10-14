"""Pure recurrence generator (F4).

Produces the list of `depart_at` datetimes a trip series yields between
its start and end. The generator depends only on the standard library so
it can be unit-tested without the web stack or the database.

Asia/Dhaka is the only supported timezone (no DST). All datetimes are
returned as timezone-aware UTC values so the database can compare them
safely with other UTC timestamps.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Iterator, List
from zoneinfo import ZoneInfo

# Monday=0 ... Sunday=6 (Python's weekday())
DHAKA = ZoneInfo("Asia/Dhaka")

# Maximum window width in minutes (F4: earliest to latest must be <= 30 min).
MAX_WINDOW_MINUTES = 30
# Maximum seats offered per trip (F4).
MAX_SEATS = 6
# Maximum note length (F4).
MAX_NOTE = 150


def to_utc(local: datetime, tz: ZoneInfo = DHAKA) -> datetime:
    """Convert a naive or aware local datetime to UTC."""
    if local.tzinfo is None:
        local = local.replace(tzinfo=tz)
    return local.astimezone(timezone.utc)


def from_utc(utc: datetime, tz: ZoneInfo = DHAKA) -> datetime:
    """Convert a UTC datetime to the local timezone."""
    if utc.tzinfo is None:
        utc = utc.replace(tzinfo=timezone.utc)
    return utc.astimezone(tz)


def window_minutes(earliest: datetime, latest: datetime) -> int:
    """Return the size of a departure window in whole minutes."""
    if latest < earliest:
        return -1
    delta = latest - earliest
    return int(delta.total_seconds() // 60)


def iter_weekly_dates(
    start_date: date,
    end_date: date,
    weekdays_mask: int,
) -> Iterator[date]:
    """Yield every date in [start_date, end_date] whose weekday bit is
    set in `weekdays_mask`. Bits: Monday=bit0 ... Sunday=bit6.
    """
    if end_date < start_date:
        return
    d = start_date
    while d <= end_date:
        bit = 1 << d.weekday()
        if weekdays_mask & bit:
            yield d
        d += timedelta(days=1)


def generate_one_off(
    earliest_local: datetime,
    horizon_end_local: datetime,
) -> List[datetime]:
    """A one-off series produces exactly one depart_at at the earliest."""
    if earliest_local > horizon_end_local:
        return []
    return [earliest_local]


def generate_weekly(
    start_local_date: date,
    end_local_date: date,
    weekdays_mask: int,
    depart_time: time,
) -> List[datetime]:
    """A weekly series produces a depart_at for every matching weekday."""
    out: List[datetime] = []
    for d in iter_weekly_dates(start_local_date, end_local_date, weekdays_mask):
        out.append(datetime.combine(d, depart_time, tzinfo=DHAKA))
    return out


def generate_series(
    *,
    recurrence_kind: str,
    series_start_local: date,
    series_end_local: date | None,
    weekdays_mask: int,
    earliest_local: datetime,
    horizon_end_local: datetime,
) -> List[datetime]:
    """Top-level entry. Returns a sorted list of timezone-aware (UTC)
    depart_at datetimes that fall within [earliest_local, horizon_end_local]."""
    if recurrence_kind == "one_off":
        candidates = generate_one_off(earliest_local, horizon_end_local)
    elif recurrence_kind == "weekly":
        if series_end_local is None:
            return []
        depart_time = earliest_local.timetz().replace(tzinfo=None)
        candidates = generate_weekly(
            series_start_local, series_end_local, weekdays_mask, depart_time,
        )
    else:
        return []
    out: List[datetime] = []
    for c in candidates:
        # Force local-then-UTC so the wall clock time matches the user's
        # intent rather than being shifted by any tzinfo arithmetic.
        if c.tzinfo is None:
            c = c.replace(tzinfo=DHAKA)
        else:
            c = c.astimezone(DHAKA)
        if c < earliest_local:
            continue
        if c > horizon_end_local:
            continue
        out.append(c.astimezone(timezone.utc))
    out.sort()
    return out
