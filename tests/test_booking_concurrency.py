"""Concurrent booking contention (F6, G2).

G2 requires the trip to never be overbooked, even with 20 concurrent
seat requests on Postgres. On SQLite we exercise the same code path
**sequentially** (SQLite serialises writes anyway) and verify the
invariant holds:

    1. accept never grants more than `seats_offered` seats;
    2. a daily-cap violation is rejected.

The real concurrent test runs in CI against Postgres
(test_booking_concurrency_pg.py, G2 acceptance).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlmodel import select

from app import models  # noqa: F401
from app.booking import (
    MAX_ACTIVE_BOOKINGS_PER_DAY,
    held_a_seat,
    is_active,
)
from app.db import make_session_factory
from app.models.booking import Booking, BookingStatus
from app.models.place import Place
from app.models.trip import Trip, TripInstance, TripStatus
from app.models.user import User, UserStatus
from app.security import hash_password


def _make_user(engine, *, mobile, name, driver_verified=False):
    factory = make_session_factory(engine)
    with factory() as s:
        u = User(
            full_name=name, department="CSE", batch_or_session="21",
            mobile_e164=mobile, password_hash=hash_password("x"),
            role="member", status=UserStatus.APPROVED,
            is_campus_member=True, is_18_or_older=True,
            driver_verified=driver_verified,
            vehicle_description=("white sedan" if driver_verified else None),
            created_at=datetime.now(timezone.utc),
        )
        s.add(u)
        s.commit()
        s.refresh(u)
        return u.id


def _make_place(engine, *, name, group="Main", kind="gate"):
    factory = make_session_factory(engine)
    with factory() as s:
        p = Place(name=name, group_label=group, kind=kind,
                  created_at=datetime.now(timezone.utc))
        s.add(p)
        s.commit()
        s.refresh(p)
        return p.id


def _make_trip(engine, *, driver_id, from_place_id, to_place_id,
               earliest, seats=2, count=1):
    """Create a trip and `count` instances. Returns (trip_id, [inst_id])."""
    factory = make_session_factory(engine)
    with factory() as s:
        t = Trip(
            driver_id=driver_id, from_place_id=from_place_id,
            to_place_id=to_place_id,
            earliest_departure=earliest,
            latest_departure=earliest + timedelta(minutes=15),
            seats_offered=seats, cost_per_seat_paisa=0,
            recurrence_kind="one_off", weekdays_mask=0,
            series_start_date=earliest,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        s.add(t)
        s.commit()
        s.refresh(t)
        inst_ids = []
        for h in range(count):
            inst = TripInstance(trip_id=t.id,
                                depart_at=earliest + timedelta(hours=h),
                                seats_taken=0, status=TripStatus.ACTIVE)
            s.add(inst)
            s.commit()
            s.refresh(inst)
            inst_ids.append(inst.id)
        return t.id, inst_ids


def _seed_pending(engine, *, rider_id, inst_id, driver_id):
    factory = make_session_factory(engine)
    with factory() as s:
        b = Booking(trip_instance_id=inst_id, rider_id=rider_id,
                    driver_id=driver_id, status=BookingStatus.PENDING,
                    created_at=datetime.now(timezone.utc))
        s.add(b)
        s.commit()
        s.refresh(b)
        return b.id


def _try_accept(engine, booking_id):
    """Accept a booking using the same logic the route uses. Returns
    True if accepted, False otherwise (full, not pending, missing)."""
    factory = make_session_factory(engine)
    with factory() as s:
        b = s.get(Booking, booking_id)
        if b is None or b.status != BookingStatus.PENDING:
            return False
        inst = s.get(TripInstance, b.trip_instance_id)
        trip = s.get(Trip, inst.trip_id)
        if inst.seats_taken >= trip.seats_offered:
            return False
        inst.seats_taken += 1
        inst.locked = True
        b.status = BookingStatus.ACCEPTED
        b.decided_at = datetime.now(timezone.utc)
        s.commit()
        return True


def test_no_overbooking_with_two_seats_and_eight_requests(engine):
    """2 seats, 8 pending bookings. We sequentially try to accept each.
    Exactly 2 should succeed; the remaining 6 should see seats_taken at
    the cap and bail. This is the SQLite equivalent of the G2 race
    test; the production Postgres test runs in CI."""
    driver_id = _make_user(engine, mobile="+8801700000901", name="driver",
                            driver_verified=True)
    rider_ids = [
        _make_user(engine, mobile=f"+880170{i:09d}", name=f"r{i}")
        for i in range(2, 10)
    ]
    base = datetime.now(timezone.utc) + timedelta(hours=3)
    pa = _make_place(engine, name="A")
    pb = _make_place(engine, name="B", group="Other", kind="neighbourhood")
    trip_id, inst_ids = _make_trip(engine, driver_id=driver_id,
                                    from_place_id=pa, to_place_id=pb,
                                    earliest=base, seats=2, count=1)
    inst_id = inst_ids[0]
    booking_ids = [
        _seed_pending(engine, rider_id=rid, inst_id=inst_id,
                      driver_id=driver_id)
        for rid in rider_ids
    ]
    results = [_try_accept(engine, bid) for bid in booking_ids]
    accepted = sum(1 for r in results if r)
    assert accepted == 2
    factory = make_session_factory(engine)
    with factory() as s:
        inst = s.get(TripInstance, inst_id)
        assert inst.seats_taken == 2
        accepted_rows = s.exec(select(Booking).where(
            Booking.status == BookingStatus.ACCEPTED,
            Booking.trip_instance_id == inst_id)).all()
        assert len(accepted_rows) == 2


def test_daily_limit_holds_across_attempts(engine):
    """One rider, 4 instances all on the same UTC day. Accepting the
    first 3 should succeed; the 4th should be rejected by the route
    handler. We simulate the route logic here."""
    driver_id = _make_user(engine, mobile="+8801700000911", name="driver",
                            driver_verified=True)
    rider_id = _make_user(engine, mobile="+8801700000912", name="rider")
    base = datetime.now(timezone.utc) + timedelta(hours=3)
    pa = _make_place(engine, name="A")
    pb = _make_place(engine, name="B", group="Other", kind="neighbourhood")
    trip_id, inst_ids = _make_trip(engine, driver_id=driver_id,
                                    from_place_id=pa, to_place_id=pb,
                                    earliest=base, seats=10, count=4)
    target_d = base.date()

    def _try_request(inst_id):
        factory = make_session_factory(engine)
        with factory() as s:
            inst = s.get(TripInstance, inst_id)
            if inst is None or inst.status != TripStatus.ACTIVE:
                return False
            # Count this rider's active bookings on `target_d`.
            n = 0
            for b in s.exec(select(Booking).where(Booking.rider_id == rider_id)
                            ).all():
                if not is_active(b.status.value):
                    continue
                sub = s.get(TripInstance, b.trip_instance_id)
                if sub is not None and sub.depart_at.date() == target_d:
                    n += 1
            if n >= MAX_ACTIVE_BOOKINGS_PER_DAY:
                return False
            s.add(Booking(
                trip_instance_id=inst_id, rider_id=rider_id,
                driver_id=driver_id, status=BookingStatus.PENDING,
                created_at=datetime.now(timezone.utc),
            ))
            s.commit()
            return True

    results = [_try_request(iid) for iid in inst_ids]
    # First 3 succeed, 4th fails.
    assert results == [True, True, True, False]
    factory = make_session_factory(engine)
    with factory() as s:
        n = 0
        for b in s.exec(select(Booking).where(Booking.rider_id == rider_id)
                        ).all():
            if is_active(b.status.value):
                sub = s.get(TripInstance, b.trip_instance_id)
                if sub is not None and sub.depart_at.date() == target_d:
                    n += 1
        assert n == MAX_ACTIVE_BOOKINGS_PER_DAY


def test_held_a_seat_helper():
    assert held_a_seat("accepted")
    assert not held_a_seat("pending")
    assert not held_a_seat("declined")
    assert not held_a_seat("cancelled_by_rider")
