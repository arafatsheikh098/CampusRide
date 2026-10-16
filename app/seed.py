"""Idempotent demo seed (F10).

Creates:
  * one moderator (mobile 01700000001, password "changeme")
  * three places: Campus Gate, Library, Bus Stand
  * a few approved drivers and riders
  * two trips (one in 2 hours, one in 2 days)

Re-running the seed is a no-op: every insert checks for an existing
row by a natural key first. Safe to run on a populated database; the
spec says idempotent.

Only runs in development; refuses to seed if `app_env == production`.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlmodel import select

from .auth import normalize_mobile
from .config import get_settings
from .db import get_engine, make_session_factory
from .models.place import Place
from .models.trip import RecurrenceKind, Trip, TripInstance, TripStatus
from .models.user import User, UserRole, UserStatus
from .security import hash_password


_PLACES = [
    ("Campus Gate", "Main", "gate"),
    ("Library", "Main", "department"),
    ("TSC", "Main", "hall"),
    ("Dhanmondi 27", "Dhanmondi", "neighbourhood"),
    ("Mirpur 10", "Mirpur", "neighbourhood"),
    ("Gulistan", "Old Dhaka", "neighbourhood"),
]

_DRIVERS = [
    ("01700000010", "Aisha Khan", "CSE", "21", "white sedan", None),
    ("01700000011", "Bilal Hossain", "EEE", "20", "blue hatchback", "DM-G-12-3456"),
    ("01700000012", "Chowdhury Reza", "BBA", "22", "black SUV", "DH-K-9-8765"),
]

_RIDERS = [
    ("01700000020", "Daniyal Islam", "CSE", "23"),
    ("01700000021", "Esha Akter", "CSE", "24"),
    ("01700000022", "Farhan Ahmed", "ME", "21"),
]


def _get_or_create_user(s, *, mobile, name, dept, batch,
                       role=UserRole.MEMBER, status=UserStatus.APPROVED,
                       driver_verified=False, vehicle_description=None,
                       vehicle_plate=None):
    norm_mobile = normalize_mobile(mobile)
    existing = s.exec(select(User).where(User.mobile_e164 == norm_mobile)).first()
    if existing is not None:
        return existing
    u = User(
        full_name=name, department=dept, batch_or_session=batch,
        mobile_e164=norm_mobile,
        password_hash=hash_password("changeme" if role == UserRole.MEMBER else "modpass1"),
        role=role, status=status,
        is_campus_member=True, is_18_or_older=True,
        driver_verified=driver_verified,
        vehicle_description=vehicle_description,
        vehicle_plate=vehicle_plate,
        created_at=datetime.now(timezone.utc),
    )
    s.add(u)
    s.flush()
    return u


def _get_or_create_place(s, *, name, group, kind):
    existing = s.exec(select(Place).where(Place.name == name)).first()
    if existing is not None:
        return existing
    p = Place(name=name, group_label=group, kind=kind,
              created_at=datetime.now(timezone.utc))
    s.add(p)
    s.flush()
    return p


def seed() -> dict:
    s = get_settings()
    if s.app_env.lower() == "production":
        raise RuntimeError("refusing to seed in production")
    eng = get_engine()
    factory = make_session_factory(eng)
    counts: dict[str, int] = {
        "users": 0, "places": 0, "trips": 0, "instances": 0,
    }
    with factory() as sess:
        # Moderator.
        mod = _get_or_create_user(
            sess, mobile="01700000001", name="Mod Mira",
            dept="CSE", batch="N/A", role=UserRole.MODERATOR,
        )
        if mod.id is not None and sess.is_modified(mod):
            counts["users"] += 1
        # Drivers.
        for mobile, name, dept, batch, veh, plate in _DRIVERS:
            _get_or_create_user(
                sess, mobile=mobile, name=name, dept=dept, batch=batch,
                driver_verified=True, vehicle_description=veh,
                vehicle_plate=plate,
            )
            counts["users"] += 1
        # Riders.
        for mobile, name, dept, batch in _RIDERS:
            _get_or_create_user(
                sess, mobile=mobile, name=name, dept=dept, batch=batch,
            )
            counts["users"] += 1
        # Places.
        for name, group, kind in _PLACES:
            _get_or_create_place(sess, name=name, group=group, kind=kind)
            counts["places"] += 1
        sess.commit()
        # One trip from each driver.
        campus = sess.exec(
            select(Place).where(Place.name == "Campus Gate")
        ).first()
        library = sess.exec(
            select(Place).where(Place.name == "Library")
        ).first()
        dhanmondi = sess.exec(
            select(Place).where(Place.name == "Dhanmondi 27")
        ).first()
        if campus is not None and library is not None and dhanmondi is not None:
            for mobile, *_ in _DRIVERS:
                norm = normalize_mobile(mobile)
                driver = sess.exec(
                    select(User).where(User.mobile_e164 == norm)
                ).first()
                if driver is None:
                    continue
                # Idempotency: don't add a second trip for the same
                # driver-route combination.
                existing_trip = sess.exec(
                    select(Trip).where(
                        Trip.driver_id == driver.id,
                        Trip.from_place_id == campus.id,
                        Trip.to_place_id == dhanmondi.id,
                    )
                ).first()
                if existing_trip is not None:
                    continue
                now = datetime.now(timezone.utc)
                departs_at = (now + timedelta(hours=2)).replace(
                    minute=0, second=0, microsecond=0,
                )
                t = Trip(
                    driver_id=driver.id,
                    from_place_id=campus.id, to_place_id=dhanmondi.id,
                    earliest_departure=departs_at,
                    latest_departure=departs_at + timedelta(minutes=15),
                    seats_offered=3, cost_per_seat_paisa=0,
                    recurrence_kind=RecurrenceKind.ONE_OFF,
                    weekdays_mask=0,
                    series_start_date=departs_at,
                    created_at=now, updated_at=now,
                )
                sess.add(t)
                sess.flush()
                inst = TripInstance(
                    trip_id=t.id, depart_at=departs_at,
                    seats_taken=0, status=TripStatus.ACTIVE,
                )
                sess.add(inst)
                sess.flush()
                counts["trips"] += 1
                counts["instances"] += 1
        sess.commit()
    return counts
