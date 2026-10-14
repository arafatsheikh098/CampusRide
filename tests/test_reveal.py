"""Pure helper tests for the reveal/blocks module (F7, F8)."""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone

from app.reveal import (
    TRUSTED_TOKEN_BYTES,
    can_reveal_contact,
    first_name,
    is_blocked_pair,
    is_trusted_link_active,
    make_trusted_token,
    post_trip_check_available,
    trusted_link_expiry,
)


def test_can_reveal_contact_only_after_acceptance():
    b_accepted = type("B", (), {"status": type("S", (), {"value": "accepted"})(),
                                 "rider_id": 1, "driver_id": 2})()
    b_pending = type("B", (), {"status": type("S", (), {"value": "pending"})(),
                               "rider_id": 1, "driver_id": 2})()
    b_declined = type("B", (), {"status": type("S", (), {"value": "declined"})(),
                                "rider_id": 1, "driver_id": 2})()
    assert can_reveal_contact(b_accepted, viewer_id=1, driver_id=2)
    assert not can_reveal_contact(b_accepted, viewer_id=99, driver_id=2)
    assert not can_reveal_contact(b_pending, viewer_id=1, driver_id=2)
    assert not can_reveal_contact(b_declined, viewer_id=1, driver_id=2)


def test_is_blocked_pair_either_direction():
    assert is_blocked_pair(1, 2, [(1, 2)])
    assert is_blocked_pair(1, 2, [(2, 1)])
    assert not is_blocked_pair(1, 2, [(3, 4)])
    assert not is_blocked_pair(1, 2, [])


def test_first_name_splits_on_space():
    assert first_name("Aisha Khan") == "Aisha"
    assert first_name("Aisha") == "Aisha"
    assert first_name("  Aisha  Khan ") == "Aisha"
    assert first_name("") == ""


def test_make_trusted_token_has_128_bits_and_unique_hash():
    t1, h1 = make_trusted_token()
    t2, h2 = make_trusted_token()
    # The raw token carries at least 32 bytes -> 256 bits.
    assert TRUSTED_TOKEN_BYTES == 32
    assert len(t1) >= 32
    assert t1 != t2
    assert h1 != h2
    # The hash should be sha256 hex.
    assert re.fullmatch(r"[0-9a-f]{64}", h1)
    assert hashlib.sha256(t1.encode("utf-8")).hexdigest() == h1


def test_trusted_link_expiry_uses_grace_after_departure():
    depart = datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc)
    now = datetime(2026, 2, 28, tzinfo=timezone.utc)
    exp = trusted_link_expiry(depart, now, grace_minutes=120)
    assert exp == depart + timedelta(minutes=120)


def test_trusted_link_expiry_handles_naive():
    depart = datetime(2026, 3, 1, 8, 0)  # naive
    now = datetime(2026, 2, 28, tzinfo=timezone.utc)
    exp = trusted_link_expiry(depart, now, grace_minutes=60)
    assert exp == depart.replace(tzinfo=timezone.utc) + timedelta(minutes=60)


def test_is_trusted_link_active_boundary():
    depart = datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc)
    exp = trusted_link_expiry(depart, depart, grace_minutes=60)
    # exactly at the boundary: still active.
    assert is_trusted_link_active(exp, depart + timedelta(minutes=60))
    assert not is_trusted_link_active(exp, depart + timedelta(minutes=61))


def test_post_trip_check_available_at_or_after_depart():
    depart = datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc)
    assert post_trip_check_available(depart, depart)
    assert post_trip_check_available(depart, depart + timedelta(hours=1))
    # not yet: before depart
    assert not post_trip_check_available(
        depart, depart - timedelta(minutes=1),
    )
