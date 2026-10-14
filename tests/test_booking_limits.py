"""Pure-helper tests for the booking limits (F6)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.booking import (
    BOOKING_REASON_MAX_LEN,
    MAX_ACTIVE_BOOKINGS_PER_DAY,
    MAX_PENDING_REQUESTS,
    count_active_for_day,
    count_pending,
    held_a_seat,
    is_active,
    is_blocked,
    is_last_minute,
    seats_left,
    validate_reason,
    within_active_day_limit,
    within_pending_limit,
)


_BASE = datetime(2026, 3, 5, 8, 0, tzinfo=timezone.utc)


def test_count_active_for_day_only_counts_same_day_active():
    bookings = [
        (_BASE, "pending"),
        (_BASE + timedelta(hours=2), "accepted"),
        (_BASE + timedelta(hours=3), "pending"),  # same day
        (_BASE + timedelta(days=1), "accepted"),  # next day
        (_BASE, "declined"),  # not active
        (_BASE, "cancelled_by_rider"),
        (_BASE, "cancelled_by_driver"),
    ]
    assert count_active_for_day(bookings, _BASE) == 3


def test_count_active_for_day_handles_naive_timestamps():
    # The DB layer stores naive datetimes (UTC). Verify they compare
    # correctly against tz-aware requests.
    naive_same_day = _BASE.replace(tzinfo=None)
    naive_next_day = (_BASE + timedelta(days=1)).replace(tzinfo=None)
    bookings = [(naive_same_day, "pending"), (naive_next_day, "accepted")]
    assert count_active_for_day(bookings, _BASE) == 1


def test_count_pending_only_counts_pending():
    bookings = [
        (_BASE, "pending"),
        (_BASE, "accepted"),
        (_BASE, "declined"),
        (_BASE, "pending"),
    ]
    assert count_pending(bookings) == 2


def test_within_active_day_limit():
    assert within_active_day_limit([], _BASE)
    bookings = [(_BASE, "pending")] * (MAX_ACTIVE_BOOKINGS_PER_DAY - 1)
    assert within_active_day_limit(bookings, _BASE)
    bookings = [(_BASE, "pending")] * MAX_ACTIVE_BOOKINGS_PER_DAY
    assert not within_active_day_limit(bookings, _BASE)


def test_within_pending_limit():
    assert within_pending_limit([])
    bookings = [(_BASE, "pending")] * (MAX_PENDING_REQUESTS - 1)
    assert within_pending_limit(bookings)
    bookings = [(_BASE, "pending")] * MAX_PENDING_REQUESTS
    assert not within_pending_limit(bookings)


def test_is_last_minute_window():
    now = _BASE
    assert is_last_minute(_BASE + timedelta(minutes=30), now, 60)
    assert not is_last_minute(_BASE + timedelta(minutes=90), now, 60)
    # Exactly at the boundary counts as last-minute.
    assert is_last_minute(_BASE + timedelta(minutes=60), now, 60)


def test_is_last_minute_handles_naive_depart():
    naive = (_BASE + timedelta(minutes=30)).replace(tzinfo=None)
    aware = _BASE
    assert is_last_minute(naive, aware, 60)


def test_validate_reason():
    assert validate_reason("") == ""
    assert validate_reason(None) == ""
    assert validate_reason("a" * BOOKING_REASON_MAX_LEN) == ""
    assert validate_reason("a" * (BOOKING_REASON_MAX_LEN + 1)) == "reason_too_long"
    assert validate_reason("  hello  ") == ""  # stripped, len under cap


def test_seats_left():
    assert seats_left(3, 0) == 3
    assert seats_left(3, 3) == 0
    assert seats_left(3, 5) == 0  # never negative


def test_is_blocked_either_direction():
    assert is_blocked(1, 2, [(1, 2)])  # rider blocked driver
    assert is_blocked(1, 2, [(2, 1)])  # driver blocked rider
    assert not is_blocked(1, 2, [])


def test_is_active_and_held_a_seat():
    assert is_active("pending")
    assert is_active("accepted")
    assert not is_active("declined")
    assert not is_active("cancelled_by_rider")
    assert not is_active("cancelled_by_driver")
    assert held_a_seat("accepted")
    assert not held_a_seat("pending")
    assert not held_a_seat("declined")
