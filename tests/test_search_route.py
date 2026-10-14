"""End-to-end search route (F5)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient

from app.db import make_session_factory
from app.models.place import Place
from app.models.trip import Trip, TripInstance, TripStatus
from app.models.user import User, UserStatus
from app.security import hash_password, new_token

_DHAKA = ZoneInfo("Asia/Dhaka")


def _make_user(engine, *, mobile, name, role="member", driver_verified=False,
               women_eligible=False):
    factory = make_session_factory(engine)
    with factory() as s:
        u = User(
            full_name=name, department="CSE", batch_or_session="21",
            mobile_e164=mobile,
            password_hash=hash_password("pwpwpwpw"),
            status=UserStatus.APPROVED, role=role,
            is_campus_member=True, is_18_or_older=True,
            driver_verified=driver_verified,
            vehicle_description=("white sedan" if driver_verified else None),
            women_only_eligible=women_eligible,
            created_at=datetime.now(timezone.utc),
        )
        s.add(u)
        s.commit()
        s.refresh(u)
        return u.id


def _make_place(engine, *, name="A", group="Main", kind="gate"):
    factory = make_session_factory(engine)
    with factory() as s:
        p = Place(name=name, group_label=group, kind=kind,
                  created_at=datetime.now(timezone.utc))
        s.add(p)
        s.commit()
        s.refresh(p)
        return p.id


def _make_trip(engine, *, driver_id, from_place_id, to_place_id,
               earliest, seats=3, cost=0, women_only=False):
    factory = make_session_factory(engine)
    with factory() as s:
        t = Trip(
            driver_id=driver_id, from_place_id=from_place_id,
            to_place_id=to_place_id,
            earliest_departure=earliest,
            latest_departure=earliest + timedelta(minutes=15),
            seats_offered=seats, cost_per_seat_paisa=cost,
            note=None, women_only=women_only,
            recurrence_kind="one_off", weekdays_mask=0,
            series_start_date=earliest, series_end_date=None,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        s.add(t)
        s.commit()
        s.refresh(t)
        inst = TripInstance(
            trip_id=t.id, depart_at=earliest, seats_taken=0,
            status=TripStatus.ACTIVE,
        )
        s.add(inst)
        s.commit()
        return t.id


def _session_cookie(uid: int, role: str, settings) -> str:
    from app.main import make_session_cookie
    return make_session_cookie(settings.secret_key, uid, role, new_token())


def _iso(dt: datetime) -> str:
    return dt.replace(tzinfo=None).isoformat(timespec="minutes")


def test_unauthenticated_search_returns_404(client: TestClient):
    r = client.get("/search")
    assert r.status_code == 404


def test_approved_member_can_view_search_form(
    client: TestClient, engine, settings,
):
    uid = _make_user(engine, mobile="+8801700000301", name="rider")
    pa = _make_place(engine, name="A")
    pb = _make_place(engine, name="B", group="Other", kind="neighbourhood")
    client.cookies.set("cr_session", _session_cookie(uid, "member", settings))
    r = client.get("/search")
    assert r.status_code == 200
    assert "search.title" not in r.text  # not a key, the value should appear
    assert "Find a ride" in r.text
    # The form should list both places.
    assert f'value="{pa}"' in r.text
    assert f'value="{pb}"' in r.text


def test_search_returns_matching_trip(
    client: TestClient, engine, settings,
):
    rid = _make_user(engine, mobile="+8801700000302", name="rider")
    did = _make_user(engine, mobile="+8801700000303", name="driver",
                     driver_verified=True)
    pa = _make_place(engine, name="A")
    pb = _make_place(engine, name="B", group="Other", kind="neighbourhood")
    # Pick a time 3h from now and express it in both UTC (for the trip)
    # and Asia/Dhaka (for the rider's window). The trip's
    # `earliest_departure` is stored as a naive UTC timestamp.
    base_utc = datetime.now(timezone.utc) + timedelta(hours=3)
    base_dhaka = base_utc.astimezone(_DHAKA)
    _make_trip(engine, driver_id=did, from_place_id=pa, to_place_id=pb,
               earliest=base_utc.replace(tzinfo=None))
    client.cookies.set("cr_session", _session_cookie(rid, "member", settings))
    earliest = base_dhaka - timedelta(minutes=5)
    latest = base_dhaka + timedelta(minutes=5)
    r = client.post(
        "/search",
        data={
            "from_place_id": str(pa),
            "to_place_id": str(pb),
            "earliest": _iso(earliest),
            "latest": _iso(latest),
        },
    )
    assert r.status_code == 200
    assert "Exact pickup" in r.text or "Same group pickup" in r.text


def test_search_does_not_show_full_trip(
    client: TestClient, engine, settings,
):
    rid = _make_user(engine, mobile="+8801700000304", name="rider")
    did = _make_user(engine, mobile="+8801700000305", name="driver",
                     driver_verified=True)
    pa = _make_place(engine, name="A")
    pb = _make_place(engine, name="B", group="Other", kind="neighbourhood")
    base_utc = datetime.now(timezone.utc) + timedelta(hours=3)
    base_dhaka = base_utc.astimezone(_DHAKA)
    trip_id = _make_trip(engine, driver_id=did, from_place_id=pa,
                         to_place_id=pb,
                         earliest=base_utc.replace(tzinfo=None), seats=1)
    # Fill the seat.
    factory = make_session_factory(engine)
    with factory() as s:
        for inst in s.exec(__import__("sqlmodel").select(TripInstance)
                            .where(TripInstance.trip_id == trip_id)):
            inst.seats_taken = 1
        s.commit()
    client.cookies.set("cr_session", _session_cookie(rid, "member", settings))
    r = client.post(
        "/search",
        data={
            "from_place_id": str(pa), "to_place_id": str(pb),
            "earliest": _iso(base_dhaka - timedelta(minutes=5)),
            "latest": _iso(base_dhaka + timedelta(minutes=5)),
        },
    )
    assert r.status_code == 200
    assert f'href="/trips/{trip_id}"' not in r.text


def test_search_rejects_same_from_and_to(
    client: TestClient, engine, settings,
):
    rid = _make_user(engine, mobile="+8801700000306", name="rider")
    pa = _make_place(engine, name="A")
    client.cookies.set("cr_session", _session_cookie(rid, "member", settings))
    r = client.post(
        "/search",
        data={
            "from_place_id": str(pa), "to_place_id": str(pa),
            "earliest": "2026-03-05T08:00", "latest": "2026-03-05T08:10",
        },
    )
    assert r.status_code == 400
    assert "different" in r.text.lower() or "From" in r.text


def test_search_rejects_reversed_window(
    client: TestClient, engine, settings,
):
    rid = _make_user(engine, mobile="+8801700000307", name="rider")
    pa = _make_place(engine, name="A")
    pb = _make_place(engine, name="B", group="Other", kind="neighbourhood")
    client.cookies.set("cr_session", _session_cookie(rid, "member", settings))
    r = client.post(
        "/search",
        data={
            "from_place_id": str(pa), "to_place_id": str(pb),
            "earliest": "2026-03-05T08:10", "latest": "2026-03-05T08:00",
        },
    )
    assert r.status_code == 400


def test_search_hides_women_only_trip_from_non_eligible_rider(
    client: TestClient, engine, settings,
):
    # Enable the feature in this test's settings snapshot.
    settings.women_only_trips = True
    rid = _make_user(engine, mobile="+8801700000308", name="rider")
    did = _make_user(engine, mobile="+8801700000309", name="driver",
                     driver_verified=True, women_eligible=True)
    pa = _make_place(engine, name="A")
    pb = _make_place(engine, name="B", group="Other", kind="neighbourhood")
    base_utc = datetime.now(timezone.utc) + timedelta(hours=3)
    base_dhaka = base_utc.astimezone(_DHAKA)
    trip_id = _make_trip(engine, driver_id=did, from_place_id=pa,
                         to_place_id=pb,
                         earliest=base_utc.replace(tzinfo=None),
                         women_only=True)
    client.cookies.set("cr_session", _session_cookie(rid, "member", settings))
    r = client.post(
        "/search",
        data={
            "from_place_id": str(pa), "to_place_id": str(pb),
            "earliest": _iso(base_dhaka - timedelta(minutes=5)),
            "latest": _iso(base_dhaka + timedelta(minutes=5)),
        },
    )
    assert r.status_code == 200
    assert f'href="/trips/{trip_id}"' not in r.text
