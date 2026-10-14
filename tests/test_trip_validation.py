"""Trip validation (F4)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.trip_validation import (
    validate_cost,
    validate_note,
    validate_recurrence,
    validate_seats,
    validate_trip,
    validate_window,
)

_DHAKA = ZoneInfo("Asia/Dhaka")


def test_validate_window_ok_30_min():
    a = datetime(2026, 3, 5, 8, 0, tzinfo=_DHAKA)
    b = datetime(2026, 3, 5, 8, 30, tzinfo=_DHAKA)
    assert validate_window(a, b) == ""


def test_validate_window_rejects_over_30_min():
    a = datetime(2026, 3, 5, 8, 0, tzinfo=_DHAKA)
    b = datetime(2026, 3, 5, 8, 31, tzinfo=_DHAKA)
    assert validate_window(a, b) == "window_too_wide"


def test_validate_window_rejects_reversed():
    a = datetime(2026, 3, 5, 8, 30, tzinfo=_DHAKA)
    b = datetime(2026, 3, 5, 8, 0, tzinfo=_DHAKA)
    assert validate_window(a, b) == "window_reversed"


def test_validate_seats():
    assert validate_seats(0) == "seats_out_of_range"
    assert validate_seats(1) == ""
    assert validate_seats(6) == ""
    assert validate_seats(7) == "seats_out_of_range"


def test_validate_cost():
    assert validate_cost(0, 50000) == ""
    assert validate_cost(50000, 50000) == ""
    assert validate_cost(50001, 50000) == "cost_over_cap"
    assert validate_cost(-1, 50000) == "cost_negative"


def test_validate_note_rejects_url():
    assert validate_note("Please visit https://x.com for the route") == "note_has_url"
    assert validate_note("visit www.example.com for info") == "note_has_url"


def test_validate_note_rejects_long_phone():
    assert validate_note("call +8801712345678 if late") == "note_has_phone"
    assert validate_note("call 01712-345678 if late") == "note_has_phone"


def test_validate_note_allows_short_or_punct():
    assert validate_note("Will wait at gate 3, ~5 min late ok") == ""


def test_validate_note_length_cap():
    assert validate_note("x" * 151) == "note_too_long"
    assert validate_note("x" * 150) == ""


def test_validate_recurrence_one_off_no_end():
    assert validate_recurrence("one_off", 0, datetime(2026, 3, 1), None) == ""


def test_validate_recurrence_weekly_requires_end():
    err = validate_recurrence("weekly", 1, datetime(2026, 3, 1), None)
    assert err == "series_end_required"


def test_validate_recurrence_weekly_requires_days():
    err = validate_recurrence("weekly", 0, datetime(2026, 3, 1), datetime(2026, 3, 8))
    assert err == "weekdays_mask"


def test_validate_trip_ok():
    err = validate_trip(
        from_place_id=1, to_place_id=2,
        earliest=datetime(2026, 3, 5, 8, 0, tzinfo=_DHAKA),
        latest=datetime(2026, 3, 5, 8, 15, tzinfo=_DHAKA),
        seats=2, cost_per_seat_paisa=5000, note="",
        recurrence_kind="one_off", weekdays_mask=0,
        series_start=datetime(2026, 3, 5), series_end=None,
        cost_cap_paisa=50000,
    )
    assert err == ""


def test_validate_trip_rejects_same_place():
    err = validate_trip(
        from_place_id=1, to_place_id=1,
        earliest=datetime(2026, 3, 5, 8, 0, tzinfo=_DHAKA),
        latest=datetime(2026, 3, 5, 8, 15, tzinfo=_DHAKA),
        seats=2, cost_per_seat_paisa=0, note="",
        recurrence_kind="one_off", weekdays_mask=0,
        series_start=datetime(2026, 3, 5), series_end=None,
        cost_cap_paisa=50000,
    )
    assert err == "same_place"
