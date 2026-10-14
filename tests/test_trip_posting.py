"""End-to-end trip posting tests (F4). Uses the FastAPI TestClient with
the conftest fixtures. Driver-verified approved members can post; non-
verified members cannot (G5). Tampered inputs (URLs, phones, past
departure) are rejected (G5).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.db import make_session_factory
from app.models.place import Place
from app.models.trip import RecurrenceKind, Trip, TripInstance
from app.models.user import User, UserStatus
from app.security import hash_password, new_token

_DHAKA = ZoneInfo("Asia/Dhaka")


def _csrf(html: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return m.group(1) if m else ""


def _make_user(
    engine, *, mobile, name="U", role="member",
    status=UserStatus.APPROVED, driver_verified=False,
):
    factory = make_session_factory(engine)
    with factory() as s:
        u = User(
            full_name=name, department="CSE", batch_or_session="21",
            mobile_e164=mobile,
            password_hash=hash_password("pwpwpwpw"),
            status=status, role=role,
            is_campus_member=True, is_18_or_older=True,
            driver_verified=driver_verified,
            vehicle_description=("white sedan" if driver_verified else None),
            created_at=datetime.now(timezone.utc),
        )
        s.add(u)
        s.commit()
        s.refresh(u)
        return u.id


def _make_place(engine, *, name="Gate A", group="Main", kind="gate"):
    factory = make_session_factory(engine)
    with factory() as s:
        p = Place(name=name, group_label=group, kind=kind,
                  created_at=datetime.now(timezone.utc))
        s.add(p)
        s.commit()
        s.refresh(p)
        return p.id


def _session_cookie(uid: int, role: str, settings) -> str:
    from app.main import make_session_cookie
    return make_session_cookie(settings.secret_key, uid, role, new_token())


def _iso(dt: datetime) -> str:
    """ISO format suitable for an <input type=datetime-local> value (no tz)."""
    return dt.replace(tzinfo=None).isoformat(timespec="minutes")


def test_unverified_member_cannot_view_new_trip_form(client: TestClient, engine, settings):
    uid = _make_user(engine, mobile="+8801700000201", name="rider")
    cookie = _session_cookie(uid, "member", settings)
    client.cookies.set("cr_session", cookie)
    assert client.get("/trips/new").status_code == 404


def test_verified_member_can_post_one_off_trip(client: TestClient, engine, settings):
    uid = _make_user(engine, mobile="+8801700000202", name="driver", driver_verified=True)
    pa = _make_place(engine, name="A", group="Main", kind="gate")
    pb = _make_place(engine, name="B", group="Main", kind="neighbourhood")
    cookie = _session_cookie(uid, "member", settings)
    client.cookies.set("cr_session", cookie)
    r = client.get("/trips/new")
    csrf = _csrf(r.text)
    earliest = datetime.now(_DHAKA) + timedelta(hours=2)
    latest = earliest + timedelta(minutes=15)
    r = client.post(
        "/trips/new",
        data={
            "from_place_id": str(pa), "to_place_id": str(pb),
            "earliest": _iso(earliest), "latest": _iso(latest),
            "seats": "2", "cost_per_seat_paisa": "5000", "note": "be on time",
            "recurrence_kind": "one_off",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    factory = make_session_factory(engine)
    with factory() as s:
        trips = s.exec(__import__("sqlmodel").select(Trip)).all()
        assert len(trips) == 1
        instances = s.exec(__import__("sqlmodel").select(TripInstance)).all()
        assert len(instances) == 1
        assert instances[0].trip_id == trips[0].id
        assert instances[0].seats_taken == 0


def test_tampered_url_in_note_is_rejected(client: TestClient, engine, settings):
    uid = _make_user(engine, mobile="+8801700000203", name="driver", driver_verified=True)
    pa = _make_place(engine, name="A")
    pb = _make_place(engine, name="B")
    cookie = _session_cookie(uid, "member", settings)
    client.cookies.set("cr_session", cookie)
    r = client.get("/trips/new")
    csrf = _csrf(r.text)
    earliest = datetime.now(_DHAKA) + timedelta(hours=2)
    r = client.post(
        "/trips/new",
        data={
            "from_place_id": str(pa), "to_place_id": str(pb),
            "earliest": _iso(earliest), "latest": _iso(earliest + timedelta(minutes=10)),
            "seats": "2", "cost_per_seat_paisa": "0",
            "note": "check https://example.com for route",
            "recurrence_kind": "one_off", "csrf_token": csrf,
        },
    )
    assert r.status_code == 400
    assert "URL" in r.text or "url" in r.text


def test_tampered_phone_in_note_is_rejected(client: TestClient, engine, settings):
    uid = _make_user(engine, mobile="+8801700000204", name="driver", driver_verified=True)
    pa = _make_place(engine, name="A")
    pb = _make_place(engine, name="B")
    cookie = _session_cookie(uid, "member", settings)
    client.cookies.set("cr_session", cookie)
    r = client.get("/trips/new")
    csrf = _csrf(r.text)
    earliest = datetime.now(_DHAKA) + timedelta(hours=2)
    r = client.post(
        "/trips/new",
        data={
            "from_place_id": str(pa), "to_place_id": str(pb),
            "earliest": _iso(earliest), "latest": _iso(earliest + timedelta(minutes=10)),
            "seats": "2", "cost_per_seat_paisa": "0",
            "note": "call +8801712345678 if late",
            "recurrence_kind": "one_off", "csrf_token": csrf,
        },
    )
    assert r.status_code == 400
    assert "phone" in r.text.lower()


def test_past_departure_is_rejected(client: TestClient, engine, settings):
    uid = _make_user(engine, mobile="+8801700000205", name="driver", driver_verified=True)
    pa = _make_place(engine, name="A")
    pb = _make_place(engine, name="B")
    cookie = _session_cookie(uid, "member", settings)
    client.cookies.set("cr_session", cookie)
    r = client.get("/trips/new")
    csrf = _csrf(r.text)
    earliest = datetime.now(_DHAKA) - timedelta(hours=2)
    r = client.post(
        "/trips/new",
        data={
            "from_place_id": str(pa), "to_place_id": str(pb),
            "earliest": _iso(earliest), "latest": _iso(earliest + timedelta(minutes=10)),
            "seats": "1", "cost_per_seat_paisa": "0", "note": "",
            "recurrence_kind": "one_off", "csrf_token": csrf,
        },
    )
    assert r.status_code == 400


def test_window_wider_than_30_min_is_rejected(client: TestClient, engine, settings):
    uid = _make_user(engine, mobile="+8801700000206", name="driver", driver_verified=True)
    pa = _make_place(engine, name="A")
    pb = _make_place(engine, name="B")
    cookie = _session_cookie(uid, "member", settings)
    client.cookies.set("cr_session", cookie)
    r = client.get("/trips/new")
    csrf = _csrf(r.text)
    earliest = datetime.now(_DHAKA) + timedelta(hours=2)
    r = client.post(
        "/trips/new",
        data={
            "from_place_id": str(pa), "to_place_id": str(pb),
            "earliest": _iso(earliest), "latest": _iso(earliest + timedelta(minutes=45)),
            "seats": "1", "cost_per_seat_paisa": "0", "note": "",
            "recurrence_kind": "one_off", "csrf_token": csrf,
        },
    )
    assert r.status_code == 400


def test_women_only_tampered_request_is_silently_disabled(
    client: TestClient, engine, settings
):
    # settings.women_only_trips=False; the form does not expose the field,
    # but a hand-crafted POST with women_only=on should be ignored.
    uid = _make_user(engine, mobile="+8801700000207", name="driver", driver_verified=True)
    pa = _make_place(engine, name="A")
    pb = _make_place(engine, name="B")
    cookie = _session_cookie(uid, "member", settings)
    client.cookies.set("cr_session", cookie)
    r = client.get("/trips/new")
    csrf = _csrf(r.text)
    earliest = datetime.now(_DHAKA) + timedelta(hours=2)
    r = client.post(
        "/trips/new",
        data={
            "from_place_id": str(pa), "to_place_id": str(pb),
            "earliest": _iso(earliest), "latest": _iso(earliest + timedelta(minutes=10)),
            "seats": "2", "cost_per_seat_paisa": "0", "note": "",
            "recurrence_kind": "one_off",
            "women_only": "on",  # tampered: feature disabled
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    factory = make_session_factory(engine)
    with factory() as s:
        trip = s.exec(__import__("sqlmodel").select(Trip)).first()
        assert trip.women_only is False


def test_weekly_recurrence_generates_correct_instances(client: TestClient, engine, settings):
    uid = _make_user(engine, mobile="+8801700000208", name="driver", driver_verified=True)
    pa = _make_place(engine, name="A")
    pb = _make_place(engine, name="B")
    cookie = _session_cookie(uid, "member", settings)
    client.cookies.set("cr_session", cookie)
    r = client.get("/trips/new")
    csrf = _csrf(r.text)
    # Pick a Monday two days from now at 08:00 local.
    base = datetime.now(_DHAKA) + timedelta(days=2)
    while base.weekday() != 0:
        base += timedelta(days=1)
    earliest = base.replace(hour=8, minute=0, second=0, microsecond=0)
    end_date = (base + timedelta(days=10)).date()  # 2 Mondays within horizon
    r = client.post(
        "/trips/new",
        data={
            "from_place_id": str(pa), "to_place_id": str(pb),
            "earliest": _iso(earliest), "latest": _iso(earliest + timedelta(minutes=10)),
            "seats": "1", "cost_per_seat_paisa": "0", "note": "",
            "recurrence_kind": "weekly",
            "weekdays": ["0"],
            "series_end": end_date.isoformat(),
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    factory = make_session_factory(engine)
    with factory() as s:
        trip = s.exec(__import__("sqlmodel").select(Trip)).first()
        assert trip.recurrence_kind == RecurrenceKind.WEEKLY
        instances = s.exec(
            __import__("sqlmodel").select(TripInstance)
            .where(TripInstance.trip_id == trip.id)
        ).all()
        # 2 Mondays within the rolling horizon
        assert len(instances) == 2
