"""Notification interface (F9). M4 wires the function calls so route code
can dispatch; the actual job-queue and Telegram integration land in M8.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

from sqlmodel import Session, select

from .models.booking import Booking, BookingStatus
from .models.notification import Notification
from .models.trip import Trip, TripInstance
from .models.user import User

# Action codes that ride the interface. Real scheduling happens in M8.
ACTION_TRIP_CANCELLED = "trip.cancelled"
ACTION_TRIP_CANCELLED_BY_RIDER = "trip.cancelled_by_rider"
ACTION_TRIP_REMOVED = "trip.removed"
ACTION_BOOKING_REQUEST = "booking.request"
ACTION_BOOKING_ACCEPTED = "booking.accepted"
ACTION_BOOKING_DECLINED = "booking.declined"
ACTION_BOOKING_CANCELLED = "booking.cancelled"


def _add(
    session: Session,
    *,
    user_id: int,
    kind: str,
    body: str,
    link: str | None = None,
) -> None:
    session.add(
        Notification(
            user_id=user_id,
            kind=kind,
            body=body[:400],
            link=link,
            read=False,
            created_at=datetime.now(timezone.utc),
        )
    )


def notify_trip_cancelled(
    session,
    *,
    instance_id: int,
    by_user: User,
    recipients: Iterable[User],
) -> None:
    """In-app notification to every recipient who had a booking on the
    given instance. M8 will also schedule a Telegram push."""
    body_kind = ACTION_TRIP_CANCELLED_BY_RIDER if by_user.id else ACTION_TRIP_CANCELLED
    for u in recipients:
        _add(
            session,
            user_id=u.id, kind=body_kind,
            body=f"Trip instance #{instance_id} was cancelled.",
            link="/bookings",
        )


def notify_trip_removed(session, *, trip_id: int, by_user: User) -> None:
    rows = session.exec(
        select(Booking).where(
            Booking.status != BookingStatus.CANCELLED_BY_RIDER,
        )
    ).all()
    for b in rows:
        inst = session.get(TripInstance, b.trip_instance_id)
        if inst is None or inst.trip_id != trip_id:
            continue
        _add(
            session,
            user_id=b.rider_id, kind=ACTION_TRIP_REMOVED,
            body=f"Trip #{trip_id} was removed by a moderator.",
            link="/bookings",
        )


def notify_booking_request(
    session, *, booking: Booking, trip: Trip,
) -> None:
    _add(
        session,
        user_id=trip.driver_id,
        kind=ACTION_BOOKING_REQUEST,
        body=f"New seat request on trip #{trip.id}.",
        link=f"/trips/{trip.id}",
    )


def notify_booking_decision(
    session, *, booking: Booking, accepted: bool,
) -> None:
    kind = ACTION_BOOKING_ACCEPTED if accepted else ACTION_BOOKING_DECLINED
    _add(
        session,
        user_id=booking.rider_id,
        kind=kind,
        body=(
            f"Your booking #{booking.id} was accepted."
            if accepted else
            f"Your booking #{booking.id} was declined."
        ),
        link="/bookings",
    )


def notify_booking_cancelled(
    session, *, booking: Booking, by_user: User,
) -> None:
    other = (
        booking.driver_id if by_user.id == booking.rider_id
        else booking.rider_id
    )
    _add(
        session,
        user_id=other,
        kind=ACTION_BOOKING_CANCELLED,
        body=(
            f"Booking #{booking.id} was cancelled by "
            f"{'the rider' if by_user.id == booking.driver_id else 'the driver'}."
        ),
        link="/bookings",
    )

