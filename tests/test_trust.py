"""Trust, blocks, reports, trusted-contact and post-trip tests (F7, F8).

These tests cover:
  * blocks route (add / remove / idempotent)
  * reports route (create, validation)
  * trusted-contact link creation + public view (G7)
  * post-trip check availability + idempotency
  * reveal helpers: contact shown only after acceptance (G3)
  * blocked pairs never see each other's trips (G6)

We test the routes via the public TestClient. Each test issues a
signed session cookie for the actor (no need to go through /auth/signin).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone


from app.db import make_session_factory
from app.main import make_session_cookie
from app.models.booking import Booking, BookingStatus
from app.models.place import Place
from app.models.trip import Trip, TripInstance, TripStatus
from app.models.trust import (
    Block,
    PostTripAnswer,
    PostTripCheck,
    Report,
    ReportReason,
)
from app.models.user import User, UserStatus
from app.security import hash_password, new_token


# --- Factories -------------------------------------------------------------


def _make_user(engine, *, mobile, name, role="member",
               status=UserStatus.APPROVED, driver_verified=False,
               women_eligible=False, vehicle_plate=None):
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
            vehicle_plate=vehicle_plate,
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
               earliest, seats=3, women_only=False):
    factory = make_session_factory(engine)
    with factory() as s:
        t = Trip(
            driver_id=driver_id, from_place_id=from_place_id,
            to_place_id=to_place_id,
            earliest_departure=earliest,
            latest_departure=earliest + timedelta(minutes=15),
            seats_offered=seats, cost_per_seat_paisa=0,
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
        s.refresh(inst)
        return t.id, inst.id


def _make_booking(engine, *, rider_id, driver_id, inst_id, status=BookingStatus.ACCEPTED):
    factory = make_session_factory(engine)
    with factory() as s:
        b = Booking(
            trip_instance_id=inst_id, rider_id=rider_id,
            driver_id=driver_id, status=status,
            created_at=datetime.now(timezone.utc),
        )
        s.add(b)
        s.commit()
        s.refresh(b)
        return b.id


def _session_cookie(uid: int, role: str, settings) -> str:
    csrf = new_token()
    return make_session_cookie(settings.secret_key, uid, role, csrf), csrf


def _signed_in(client, uid, role, settings):
    cookie, csrf = _session_cookie(uid, role, settings)
    client.cookies.set("cr_session", cookie)
    return csrf


# --- Blocks ----------------------------------------------------------------


def test_blocks_add_and_remove(engine, client, settings):
    uid = _make_user(engine, mobile="+8801700000701", name="Aisha")
    other = _make_user(engine, mobile="+8801700000702", name="Bilal")
    csrf = _signed_in(client, uid, "member", settings)
    # Add
    r = client.post(
        "/blocks/add",
        data={"blocked_id": str(other), "csrf_token": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 303
    factory = make_session_factory(engine)
    with factory() as s:
        b = s.get(Block, 1)
        assert b is not None
        assert b.blocker_id == uid
        assert b.blocked_id == other
    # Listing shows the blocked user.
    r = client.get("/blocks")
    assert r.status_code == 200
    assert "Bilal" in r.text
    # Idempotent: adding again is a 303 with no duplicate row.
    r = client.post(
        "/blocks/add",
        data={"blocked_id": str(other), "csrf_token": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 303
    with factory() as s:
        from sqlmodel import select
        rows = s.exec(select(Block).where(Block.blocker_id == uid)).all()
        assert len(rows) == 1
    # Self-block silently ignored.
    r = client.post(
        "/blocks/add",
        data={"blocked_id": str(uid), "csrf_token": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 303
    # Remove.
    r = client.post(
        "/blocks/1/remove",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 303
    with factory() as s:
        assert s.get(Block, 1) is None


def test_blocks_require_csrf(engine, client, settings):
    uid = _make_user(engine, mobile="+8801700000711", name="Aisha")
    other = _make_user(engine, mobile="+8801700000712", name="Bilal")
    _signed_in(client, uid, "member", settings)
    r = client.post(
        "/blocks/add",
        data={"blocked_id": str(other), "csrf_token": "wrong"},
        follow_redirects=False,
    )
    # CSRF check fails before anything else.
    assert r.status_code in (400, 403)


# --- Reports ---------------------------------------------------------------


def test_report_create(engine, client, settings):
    me = _make_user(engine, mobile="+8801700000721", name="Aisha")
    other = _make_user(engine, mobile="+8801700000722", name="Bilal")
    csrf = _signed_in(client, me, "member", settings)
    r = client.post(
        "/reports/new",
        data={
            "target_user_id": str(other),
            "target_trip_id": "0",
            "reason": "safety",
            "note": "acted unsafe",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    factory = make_session_factory(engine)
    with factory() as s:
        rep = s.get(Report, 1)
        assert rep is not None
        assert rep.reporter_id == me
        assert rep.target_user_id == other
        assert rep.reason == ReportReason.SAFETY


def test_report_rejects_no_target(engine, client, settings):
    me = _make_user(engine, mobile="+8801700000731", name="Aisha")
    csrf = _signed_in(client, me, "member", settings)
    r = client.post(
        "/reports/new",
        data={
            "target_user_id": "0", "target_trip_id": "0",
            "reason": "other", "note": "",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert r.status_code == 400


def test_report_rejects_bad_reason(engine, client, settings):
    me = _make_user(engine, mobile="+8801700000741", name="Aisha")
    other = _make_user(engine, mobile="+8801700000742", name="Bilal")
    csrf = _signed_in(client, me, "member", settings)
    r = client.post(
        "/reports/new",
        data={
            "target_user_id": str(other), "target_trip_id": "0",
            "reason": "bogus", "note": "",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert r.status_code == 400


# --- Trusted-contact link (F7, G7) -----------------------------------------


def test_trusted_link_creation_requires_accepted_booking(
    engine, client, settings,
):
    drv = _make_user(engine, mobile="+8801700000801", name="Driver Dan",
                     driver_verified=True)
    rid = _make_user(engine, mobile="+8801700000802", name="Rider Ri")
    pa = _make_place(engine, name="A")
    pb = _make_place(engine, name="B", group="Other", kind="neighbourhood")
    earliest = datetime.now(timezone.utc) + timedelta(hours=2)
    trip_id, inst_id = _make_trip(
        engine, driver_id=drv, from_place_id=pa, to_place_id=pb,
        earliest=earliest,
    )
    csrf = _signed_in(client, rid, "member", settings)
    # Pending booking -> 403.
    _make_booking(engine, rider_id=rid, driver_id=drv, inst_id=inst_id,
                  status=BookingStatus.PENDING)
    r = client.post(
        f"/trips/{trip_id}/instances/{inst_id}/trusted-link",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 403
    # Promote to accepted and retry.
    factory = make_session_factory(engine)
    with factory() as s:
        b = s.get(Booking, 1)
        b.status = BookingStatus.ACCEPTED
        s.commit()
    r = client.post(
        f"/trips/{trip_id}/instances/{inst_id}/trusted-link",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 303
    # The redirect carries the raw token in the query string (one-shot).
    assert "trusted_token=" in r.headers["location"]


def test_trusted_link_view_only_exposes_safe_fields(
    engine, client, settings,
):
    drv = _make_user(engine, mobile="+8801700000811", name="Driver Dan",
                     driver_verified=True, vehicle_plate="DH-1234")
    rid = _make_user(engine, mobile="+8801700000812", name="Rider Ri")
    pa = _make_place(engine, name="Campus Gate")
    pb = _make_place(engine, name="Bus Stand", group="Other",
                     kind="neighbourhood")
    earliest = datetime.now(timezone.utc) + timedelta(hours=2)
    trip_id, inst_id = _make_trip(
        engine, driver_id=drv, from_place_id=pa, to_place_id=pb,
        earliest=earliest,
    )
    _make_booking(engine, rider_id=rid, driver_id=drv, inst_id=inst_id,
                  status=BookingStatus.ACCEPTED)
    csrf = _signed_in(client, rid, "member", settings)
    r = client.post(
        f"/trips/{trip_id}/instances/{inst_id}/trusted-link",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 303
    qs = r.headers["location"].split("trusted_token=", 1)[1]
    # Public view, no cookies.
    client.cookies.clear()
    r = client.get(f"/trusted/{qs}")
    assert r.status_code == 200
    body = r.text
    # Safe fields.
    assert "Driver" in body
    assert "Campus Gate" in body
    assert "Bus Stand" in body
    # Banned fields must not appear anywhere in the public page.
    assert "Driver Dan" not in body  # only first name shown
    assert "01700000811" not in body  # mobile
    assert "01700000812" not in body
    assert "DH-1234" not in body  # plate
    # Only the first name is shown.
    assert "Driver" in body and "Dan" not in body
    # Vehicle description IS shown on the public trusted page.
    assert "white sedan" in body


def test_trusted_link_expires(engine, client, settings):
    """G7: an expired link is rejected, even if the token is correct."""
    drv = _make_user(engine, mobile="+8801700000821", name="Driver Dan",
                     driver_verified=True)
    rid = _make_user(engine, mobile="+8801700000822", name="Rider Ri")
    pa = _make_place(engine, name="A")
    pb = _make_place(engine, name="B", group="Other", kind="neighbourhood")
    # Trip long past; the link expires 2h after depart.
    earliest = datetime.now(timezone.utc) - timedelta(days=2)
    trip_id, inst_id = _make_trip(
        engine, driver_id=drv, from_place_id=pa, to_place_id=pb,
        earliest=earliest,
    )
    _make_booking(engine, rider_id=rid, driver_id=drv, inst_id=inst_id,
                  status=BookingStatus.ACCEPTED)
    # Build a token directly, hash it, write the row with an already-past
    # expires_at.
    from app.reveal import make_trusted_token
    raw, h = make_trusted_token()
    from app.models.trust import TrustedContactLink
    factory = make_session_factory(engine)
    with factory() as s:
        s.add(TrustedContactLink(
            booking_id=1, trip_instance_id=inst_id, created_by_id=rid,
            token_hash=h,
            created_at=datetime.now(timezone.utc) - timedelta(days=3),
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        ))
        s.commit()
    r = client.get(f"/trusted/{raw}")
    assert r.status_code == 410
    assert "expired" in r.text.lower()


def test_trusted_link_invalid_token_404(client):
    r = client.get("/trusted/not-a-real-token")
    assert r.status_code == 404


# --- Post-trip check -------------------------------------------------------


def test_post_trip_check_idempotent(engine, client, settings):
    drv = _make_user(engine, mobile="+8801700000901", name="Driver Dan",
                     driver_verified=True)
    rid = _make_user(engine, mobile="+8801700000902", name="Rider Ri")
    pa = _make_place(engine, name="A")
    pb = _make_place(engine, name="B", group="Other", kind="neighbourhood")
    earliest = datetime.now(timezone.utc) - timedelta(hours=2)
    trip_id, inst_id = _make_trip(
        engine, driver_id=drv, from_place_id=pa, to_place_id=pb,
        earliest=earliest,
    )
    bid = _make_booking(engine, rider_id=rid, driver_id=drv, inst_id=inst_id,
                        status=BookingStatus.ACCEPTED)
    csrf = _signed_in(client, rid, "member", settings)
    r = client.post(
        f"/bookings/{bid}/check",
        data={"answer": "ok", "note": "", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 303
    # Second answer is a no-op redirect.
    r = client.post(
        f"/bookings/{bid}/check",
        data={"answer": "problem", "note": "", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 303
    factory = make_session_factory(engine)
    with factory() as s:
        rows = s.query(PostTripCheck).all() if hasattr(s, "query") else None
        from sqlmodel import select
        rows = s.exec(
            select(PostTripCheck).where(PostTripCheck.responder_id == rid)
        ).all()
        assert len(rows) == 1
        assert rows[0].answer == PostTripAnswer.OK


def test_post_trip_check_rejected_before_depart(engine, client, settings):
    drv = _make_user(engine, mobile="+8801700000911", name="Driver Dan",
                     driver_verified=True)
    rid = _make_user(engine, mobile="+8801700000912", name="Rider Ri")
    pa = _make_place(engine, name="A")
    pb = _make_place(engine, name="B", group="Other", kind="neighbourhood")
    earliest = datetime.now(timezone.utc) + timedelta(hours=3)
    trip_id, inst_id = _make_trip(
        engine, driver_id=drv, from_place_id=pa, to_place_id=pb,
        earliest=earliest,
    )
    bid = _make_booking(engine, rider_id=rid, driver_id=drv, inst_id=inst_id,
                        status=BookingStatus.ACCEPTED)
    csrf = _signed_in(client, rid, "member", settings)
    r = client.post(
        f"/bookings/{bid}/check",
        data={"answer": "ok", "note": "", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 400


# --- G3: contact reveal ---------------------------------------------------


def test_trip_detail_hides_contact_before_acceptance(
    engine, client, settings,
):
    drv = _make_user(engine, mobile="+8801700001001", name="Driver Dan",
                     driver_verified=True, vehicle_plate="DH-9999")
    rid = _make_user(engine, mobile="+8801700001002", name="Rider Ri")
    other = _make_user(engine, mobile="+8801700001003", name="Other Out")
    pa = _make_place(engine, name="A")
    pb = _make_place(engine, name="B", group="Other", kind="neighbourhood")
    earliest = datetime.now(timezone.utc) + timedelta(hours=2)
    trip_id, inst_id = _make_trip(
        engine, driver_id=drv, from_place_id=pa, to_place_id=pb,
        earliest=earliest,
    )
    _make_booking(engine, rider_id=rid, driver_id=drv, inst_id=inst_id,
                  status=BookingStatus.PENDING)
    # An outside approved member views the page.
    _signed_in(client, other, "member", settings)
    r = client.get(f"/trips/{trip_id}")
    assert r.status_code == 200
    body = r.text
    # Mobile / plate / trusted-link button must not appear.
    assert "01700001001" not in body
    assert "DH-9999" not in body
    assert "white sedan" not in body
    # Driver first name is fine; full name is not in a separate column.
    assert "Driver Dan" not in body
    # The pending requester does not see contact either.
    _signed_in(client, rid, "member", settings)
    r = client.get(f"/trips/{trip_id}")
    assert "01700001001" not in r.text
    assert "white sedan" not in r.text


def test_trip_detail_reveals_after_acceptance(engine, client, settings):
    drv = _make_user(engine, mobile="+8801700001101", name="Driver Dan",
                     driver_verified=True, vehicle_plate="DH-7777")
    rid = _make_user(engine, mobile="+8801700001102", name="Rider Ri")
    pa = _make_place(engine, name="A")
    pb = _make_place(engine, name="B", group="Other", kind="neighbourhood")
    earliest = datetime.now(timezone.utc) + timedelta(hours=2)
    trip_id, inst_id = _make_trip(
        engine, driver_id=drv, from_place_id=pa, to_place_id=pb,
        earliest=earliest,
    )
    _make_booking(engine, rider_id=rid, driver_id=drv, inst_id=inst_id,
                  status=BookingStatus.ACCEPTED)
    _signed_in(client, rid, "member", settings)
    r = client.get(f"/trips/{trip_id}")
    body = r.text
    # Now the rider sees mobile + vehicle.
    assert "01700001101" in body
    assert "white sedan" in body
    assert "DH-7777" in body


def test_outside_user_never_sees_contact_even_after_someone_accepted(
    engine, client, settings,
):
    drv = _make_user(engine, mobile="+8801700001201", name="Driver Dan",
                     driver_verified=True, vehicle_plate="DH-5555")
    rid = _make_user(engine, mobile="+8801700001202", name="Rider Ri")
    other = _make_user(engine, mobile="+8801700001203", name="Other Out")
    pa = _make_place(engine, name="A")
    pb = _make_place(engine, name="B", group="Other", kind="neighbourhood")
    earliest = datetime.now(timezone.utc) + timedelta(hours=2)
    trip_id, inst_id = _make_trip(
        engine, driver_id=drv, from_place_id=pa, to_place_id=pb,
        earliest=earliest,
    )
    _make_booking(engine, rider_id=rid, driver_id=drv, inst_id=inst_id,
                  status=BookingStatus.ACCEPTED)
    # Outside user looks at the trip.
    _signed_in(client, other, "member", settings)
    r = client.get(f"/trips/{trip_id}")
    body = r.text
    assert "01700001201" not in body
    assert "01700001202" not in body
    assert "white sedan" not in body
    assert "DH-5555" not in body


# --- G6: blocked pairs cannot book each other -----------------------------


def test_blocked_pair_cannot_request_seat(engine, client, settings):
    drv = _make_user(engine, mobile="+8801700001301", name="Driver Dan",
                     driver_verified=True)
    rid = _make_user(engine, mobile="+8801700001302", name="Rider Ri")
    pa = _make_place(engine, name="A")
    pb = _make_place(engine, name="B", group="Other", kind="neighbourhood")
    earliest = datetime.now(timezone.utc) + timedelta(hours=2)
    trip_id, inst_id = _make_trip(
        engine, driver_id=drv, from_place_id=pa, to_place_id=pb,
        earliest=earliest,
    )
    # Driver blocks the rider.
    factory = make_session_factory(engine)
    with factory() as s:
        s.add(Block(
            blocker_id=drv, blocked_id=rid,
            created_at=datetime.now(timezone.utc),
        ))
        s.commit()
    csrf = _signed_in(client, rid, "member", settings)
    r = client.post(
        "/bookings/new",
        data={
            "trip_instance_id": str(inst_id), "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert r.status_code == 403
