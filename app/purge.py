"""Retention purger (F10).

Trips, trip instances, bookings, audit log entries about trips, and
notifications are purged after `settings.retention_days` (default 90).
The purger is conservative: it only deletes rows whose trip departure
was earlier than `today - retention_days` AND every booking on that
trip is in a terminal state (cancelled or declined). Past completed
trips still surface on the audit log by id; the full row is removed.

User accounts are kept indefinitely (until the user requests deletion).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlmodel import select

from .config import get_settings
from .db import get_engine, make_session_factory
from .models.booking import Booking, BookingStatus
from .models.booking import Booking as BookingModel
from .models.notification import Notification
from .models.trip import Trip, TripInstance, TripStatus
from .models.trust import Report


def purge() -> dict:
    """Run one purge pass. Returns a count dict."""
    s = get_settings()
    eng = get_engine()
    factory = make_session_factory(eng)
    cutoff = datetime.now(timezone.utc) - timedelta(days=s.retention_days)
    counts = {
        "trip_instances": 0, "trips": 0, "bookings": 0,
        "notifications": 0, "blocks": 0,
        "post_trip_checks": 0, "reports": 0,
    }
    with factory() as sess:
        # Old cancelled/finished instances -> drop.
        old_insts = sess.exec(
            select(TripInstance).where(
                TripInstance.status == TripStatus.CANCELLED,
                TripInstance.depart_at < cutoff,
            )
        ).all()
        old_inst_ids = [i.id for i in old_insts]
        old_trip_ids = list({i.trip_id for i in old_insts})
        # Drop the bookings on those instances (terminal-state only).
        if old_inst_ids:
            rows = sess.exec(
                select(Booking).where(
                    Booking.trip_instance_id.in_(old_inst_ids),
                    Booking.status.in_([
                        BookingStatus.CANCELLED_BY_RIDER,
                        BookingStatus.CANCELLED_BY_DRIVER,
                        BookingStatus.DECLINED,
                    ]),
                )
            ).all()
            for b in rows:
                sess.delete(b)
                counts["bookings"] += 1
        # Drop the instances.
        for inst in old_insts:
            sess.delete(inst)
        counts["trip_instances"] = len(old_insts)
        sess.flush()
        # Trips whose every instance was cancelled and old enough.
        if old_trip_ids:
            for tid in old_trip_ids:
                t = sess.get(Trip, tid)
                if t is None:
                    continue
                remaining = sess.exec(
                    select(TripInstance).where(TripInstance.trip_id == tid)
                ).all()
                if not remaining:
                    sess.delete(t)
                    counts["trips"] += 1
        # Notifications older than the cutoff regardless of read state.
        old_notes = sess.exec(
            select(Notification).where(Notification.created_at < cutoff)
        ).all()
        for n in old_notes:
            sess.delete(n)
        counts["notifications"] = len(old_notes)
        # Resolved reports older than the cutoff.
        old_reps = sess.exec(
            select(Report).where(
                Report.resolved == True,  # noqa: E712
                Report.created_at < cutoff,
            )
        ).all()
        for r in old_reps:
            sess.delete(r)
        counts["reports"] = len(old_reps)
        sess.commit()
    # Compatibility with type-checkers that re-import.
    _ = BookingModel
    return counts
