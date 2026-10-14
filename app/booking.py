"""Pure booking helpers (F6)."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Set, Tuple

# Limits (F6). Configurable in code; tests use the defaults.
MAX_ACTIVE_BOOKINGS_PER_DAY = 3
MAX_PENDING_REQUESTS = 10
BOOKING_REASON_MAX_LEN = 120


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        # Treat naive as UTC (SQLite default).
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _local_date_of(dt: datetime) -> date:
    """Return the calendar date the rider's `depart_at` falls on in UTC.

    For the rider's "active bookings per day" limit we use the same
    timezone that the trip's `depart_at` is stored in (UTC).
    """
    return _to_utc(dt).date()


def count_active_for_day(
    bookings: Iterable[Tuple[datetime, str]],
    target_depart: datetime,
) -> int:
    """How many of the rider's bookings are on the same UTC day as
    `target_depart` and still active? `bookings` is a sequence of
    (depart_at, status) tuples; status is the BookingStatus value
    (e.g. "pending", "accepted", "cancelled_by_rider", "declined",
    "cancelled_by_driver"). Only pending/accepted count.
    """
    target_d = _local_date_of(target_depart)
    n = 0
    for depart, status in bookings:
        if status in ("pending", "accepted") and _local_date_of(depart) == target_d:
            n += 1
    return n


def count_pending(
    bookings: Iterable[Tuple[datetime, str]],
) -> int:
    n = 0
    for _, status in bookings:
        if status == "pending":
            n += 1
    return n


def within_active_day_limit(
    bookings: Iterable[Tuple[datetime, str]],
    target_depart: datetime,
    limit: int = MAX_ACTIVE_BOOKINGS_PER_DAY,
) -> bool:
    return count_active_for_day(bookings, target_depart) < limit


def within_pending_limit(
    bookings: Iterable[Tuple[datetime, str]],
    limit: int = MAX_PENDING_REQUESTS,
) -> bool:
    return count_pending(bookings) < limit


def is_last_minute(
    depart_at: datetime,
    now: datetime,
    window_minutes: int,
) -> bool:
    """A cancellation is "last-minute" if the trip is less than
    `window_minutes` away at the time of cancellation."""
    delta = _to_utc(depart_at) - _to_utc(now)
    return delta <= timedelta(minutes=window_minutes)


def validate_reason(reason: str | None) -> str:
    if not reason:
        return ""
    r = reason.strip()
    if len(r) > BOOKING_REASON_MAX_LEN:
        return "reason_too_long"
    return ""


def seats_left(seats_offered: int, seats_taken: int) -> int:
    return max(0, seats_offered - seats_taken)


def is_blocked(
    rider_id: int, driver_id: int, blocks: Iterable[Tuple[int, int]],
) -> bool:
    """blocks yields (blocker_id, blocked_id) pairs."""
    for b_blocker, b_blocked in blocks:
        if (b_blocker == rider_id and b_blocked == driver_id) or (
            b_blocker == driver_id and b_blocked == rider_id
        ):
            return True
    return False


# Statuses a driver is allowed to act on (accept/decline).
DRIVER_DECIDABLE_STATUSES: Set[str] = {"pending"}


# Statuses that are still "active" (the rider or driver can act on them
# or the booking is in flight). Pending and accepted count.
ACTIVE_STATUSES: Set[str] = {"pending", "accepted"}


def is_active(status: str) -> bool:
    return status in ACTIVE_STATUSES


def held_a_seat(status: str) -> bool:
    """True if this booking status held a seat. Used to decide whether
    a state transition should release the seat back to the instance."""
    return status == "accepted"
