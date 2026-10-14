"""Trip validation helpers (F4).

Pure functions: return an error string or "".
"""
from __future__ import annotations

import re
from datetime import datetime

from .recurrence import MAX_NOTE, MAX_SEATS, MAX_WINDOW_MINUTES, window_minutes

# Conservative phone detector: 8+ consecutive digits with optional + and
# dashes/spaces between. The trip note must not contain a phone number.
_PHONE_RE = re.compile(
    r"(\+?\d[\d\-\s]{7,}\d)", re.ASCII,
)
# URL detector: anything that looks like a URL.
_URL_RE = re.compile(r"(https?://|www\.)", re.IGNORECASE)


def validate_note(note: str | None) -> str:
    if note is None:
        return ""
    note = note.strip()
    if len(note) > MAX_NOTE:
        return "note_too_long"
    if _URL_RE.search(note):
        return "note_has_url"
    # Strip dashes and spaces before the phone match so a "01-234-567"
    # address (which is just a date with hyphens) is not flagged.
    if _PHONE_RE.search(note):
        # Whitelist a few false-positives: pure year numbers, dates.
        compact = re.sub(r"[\s\-]", "", note)
        if re.search(r"\d{8,}", compact):
            return "note_has_phone"
    return ""


def validate_window(earliest: datetime, latest: datetime) -> str:
    if latest < earliest:
        return "window_reversed"
    w = window_minutes(earliest, latest)
    if w < 0:
        return "window_reversed"
    if w > MAX_WINDOW_MINUTES:
        return "window_too_wide"
    return ""


def validate_seats(seats: int) -> str:
    if not isinstance(seats, int) or seats < 1 or seats > MAX_SEATS:
        return "seats_out_of_range"
    return ""


def validate_cost(cost: int, cap_paisa: int) -> str:
    if not isinstance(cost, int) or cost < 0:
        return "cost_negative"
    if cost > cap_paisa:
        return "cost_over_cap"
    return ""


def validate_recurrence(
    kind: str,
    weekdays_mask: int,
    series_start: datetime,
    series_end: datetime | None,
) -> str:
    if kind not in ("one_off", "weekly"):
        return "recurrence_kind"
    if kind == "weekly":
        if series_end is None:
            return "series_end_required"
        if series_end < series_start:
            return "series_end_before_start"
        if weekdays_mask <= 0 or weekdays_mask >= 128:
            return "weekdays_mask"
    return ""


def validate_trip(
    *,
    from_place_id: int,
    to_place_id: int,
    earliest: datetime,
    latest: datetime,
    seats: int,
    cost_per_seat_paisa: int,
    note: str | None,
    recurrence_kind: str,
    weekdays_mask: int,
    series_start: datetime,
    series_end: datetime | None,
    cost_cap_paisa: int,
) -> str:
    if from_place_id == to_place_id:
        return "same_place"
    for err, ok in (
        (validate_window(earliest, latest), None),
        (validate_seats(seats), None),
        (validate_cost(cost_per_seat_paisa, cost_cap_paisa), None),
        (validate_note(note), None),
        (validate_recurrence(recurrence_kind, weekdays_mask, series_start, series_end), None),
    ):
        if err:
            return err
    return ""
