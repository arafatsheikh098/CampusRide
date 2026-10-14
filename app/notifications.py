"""Notification interface (F9). M4 wires the function calls so route code
can dispatch; the actual job-queue and Telegram integration land in M8.
"""
from __future__ import annotations

from typing import Iterable

from .models.user import User

# Action codes that ride the interface. Real scheduling happens in M8.
ACTION_TRIP_CANCELLED = "trip.cancelled"
ACTION_TRIP_CANCELLED_BY_RIDER = "trip.cancelled_by_rider"
ACTION_TRIP_REMOVED = "trip.removed"


def notify_trip_cancelled(
    session,
    *,
    instance_id: int,
    by_user: User,
    recipients: Iterable[User],
) -> None:
    """Schedule a `trip.cancelled` notification to every recipient who
    had a booking on the given instance. M8 will turn this into a Job;
    for now it is a no-op.
    """
    return None


def notify_trip_removed(session, *, trip_id: int, by_user: User) -> None:
    """Schedule a `trip.removed` notification to anyone with a booking
    on any instance of the trip. M4 no-op; M8 wires it up.
    """
    return None
