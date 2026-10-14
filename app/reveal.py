"""Reveal, blocks, trusted-contact helpers (F7, F8).

These functions are pure: they take loaded rows and return booleans or
plain strings. No web framework, no database calls. Routes and tests
call them to decide what to show and whether to allow an action.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional, Tuple

from .models.booking import Booking
from .models.trip import TripInstance
from .security import hash_token


# A token must encode >=128 bits of entropy. `secrets.token_urlsafe(32)`
# gives 32 random bytes (256 bits) encoded in base64url -> ~43 chars.
TRUSTED_TOKEN_BYTES = 32

# Default post-trip grace period before a trusted link expires.
TRUSTED_LINK_GRACE_MINUTES = 120

# A post-trip check is available from the trip's depart time.
POST_TRIP_CHECK_DELAY_MINUTES = 0


def can_reveal_contact(
    booking: Booking,
    *,
    viewer_id: int,
    driver_id: int,
) -> bool:
    """Contact details are revealed only after acceptance, and only to the
    two parties on that booking. Pending / declined / cancelled bookings
    never reveal."""
    if booking.driver_id != driver_id:
        return False
    if viewer_id not in (booking.rider_id, driver_id):
        return False
    return booking.status.value == "accepted"


def is_blocked_pair(
    rider_id: int,
    driver_id: int,
    blocks: Iterable[Tuple[int, int]],
) -> bool:
    for b_blocker, b_blocked in blocks:
        if (b_blocker == rider_id and b_blocked == driver_id) or (
            b_blocker == driver_id and b_blocked == rider_id
        ):
            return True
    return False


def first_name(full_name: str) -> str:
    """The reveal spec: drivers and riders see each other's first name only."""
    if not full_name:
        return ""
    return full_name.split()[0].strip()


def make_trusted_token() -> Tuple[str, str]:
    """Return (raw_token, sha256_hex_hash). The raw token is what the rider
    copies; the hash is what the database stores."""
    raw = secrets.token_urlsafe(TRUSTED_TOKEN_BYTES)
    return raw, hash_token(raw)


def trusted_link_expiry(
    depart_at: datetime,
    now: datetime,
    grace_minutes: int = TRUSTED_LINK_GRACE_MINUTES,
) -> datetime:
    """Default: depart_at + grace_minutes. Stays in UTC."""
    if depart_at.tzinfo is None:
        depart_at = depart_at.replace(tzinfo=timezone.utc)
    return depart_at.astimezone(timezone.utc) + timedelta(minutes=grace_minutes)


def is_trusted_link_active(
    expires_at: datetime,
    now: datetime,
) -> bool:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now <= expires_at.astimezone(timezone.utc)


def post_trip_check_available(
    depart_at: datetime,
    now: datetime,
    delay_minutes: int = POST_TRIP_CHECK_DELAY_MINUTES,
) -> bool:
    if depart_at.tzinfo is None:
        depart_at = depart_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return now >= depart_at.astimezone(timezone.utc) - timedelta(minutes=delay_minutes)


def trusted_link_payload(
    instance: TripInstance,
    *,
    driver_first_name: str,
    vehicle_description: Optional[str],
    from_place_label: str,
    to_place_label: str,
) -> dict:
    """The fields the public trusted-contact page is allowed to show. No
    mobile, no plate, no exact full name."""
    return {
        "from": from_place_label,
        "to": to_place_label,
        "depart_at": instance.depart_at,
        "driver_first_name": driver_first_name,
        "vehicle_description": vehicle_description or "",
    }
