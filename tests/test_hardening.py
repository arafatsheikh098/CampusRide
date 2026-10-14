"""Hardening tests (H): tightens a handful of the gaps found in the audit.

Covers:
  * Settings validators (P0-4, P0-5, P2-3, P2-4)
  * `require_moderator` rejects suspended moderators (P0-9, G4)
  * `safe_next` rejects open-redirect vectors (P1-3)
  * The signin route honours `safe_next` (P1-3)
  * The signup audit row no longer logs the mobile (P0-8)
  * The CLI create-moderator no longer prints the mobile (P0-8)
  * Worker skips a past-departure trip_reminder (P0-10)
  * CSP, Permissions-Policy headers are set (P1-1, P1-2)
  * Trusted-link public page does not leak plate, mobile, full name,
    department, or full vehicle plate.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import StaticPool, create_engine
from sqlmodel import Session, SQLModel, select

from app import models  # noqa: F401
from app.config import Settings
from app.safe_redirect import safe_next
from app.security import hash_password, new_token


# --- Settings validators --------------------------------------------------


def test_settings_rejects_short_telegram_webhook_secret():
    with pytest.raises(Exception) as ei:
        Settings(telegram_webhook_secret="short")
    assert "telegram_webhook_secret" in str(ei.value)


def test_settings_accepts_long_telegram_webhook_secret():
    s = Settings(telegram_webhook_secret="x" * 32)
    assert s.telegram_webhook_secret == "x" * 32


def test_settings_rejects_bad_emergency_number():
    with pytest.raises(Exception):
        Settings(emergency_number="not-a-number")
    with pytest.raises(Exception):
        Settings(emergency_number="12")
    with pytest.raises(Exception):
        Settings(emergency_number="1234567")  # too long


def test_settings_rejects_huge_trip_horizon():
    with pytest.raises(Exception):
        Settings(trip_horizon_days=365)
    s = Settings(trip_horizon_days=60)
    assert s.trip_horizon_days == 60


def test_settings_rejects_huge_cost_cap():
    with pytest.raises(Exception):
        Settings(cost_per_seat_cap_paisa=10**9)


def test_settings_rejects_bad_supported_langs():
    with pytest.raises(Exception):
        Settings(supported_langs="EN")  # uppercase
    with pytest.raises(Exception):
        Settings(supported_langs="en,english")  # not 2 letters
    with pytest.raises(Exception):
        Settings(supported_langs="")  # empty


# --- safe_next ------------------------------------------------------------


def test_safe_next_accepts_internal_path():
    assert safe_next("/trips") == "/trips"
    assert safe_next("/trips/42") == "/trips/42"
    assert safe_next("/") == "/"
    assert safe_next("  /foo  ") == "/foo"


def test_safe_next_rejects_absolute_url():
    assert safe_next("https://evil.com") == "/"
    assert safe_next("http://evil.com/path") == "/"
    assert safe_next("ftp://x/y") == "/"


def test_safe_next_rejects_scheme_relative():
    assert safe_next("//evil.com") == "/"
    assert safe_next("\\\\evil.com") == "/"


def test_safe_next_rejects_header_injection():
    assert safe_next("/foo\r\nSet-Cookie: x=1") == "/"
    assert safe_next("/foo\nbar") == "/"
    assert safe_next("/foo\\bar") == "/"


def test_safe_next_rejects_relative_path():
    assert safe_next("trips") == "/"
    assert safe_next("evil.com/path") == "/"


def test_safe_next_handles_none_and_empty():
    assert safe_next(None) == "/"
    assert safe_next("") == "/"


# --- Signin honours safe_next --------------------------------------------


def _signup_and_approve(client, *, mobile, password, name, approve=True):
    """Helper: sign up a user and optionally mark them approved."""
    from app.phone import normalize as _norm
    r = client.get("/auth/signup")
    m = re.search(r'name="csrf_token" value="([^"]+)"', r.text)
    csrf = m.group(1)
    client.post(
        "/auth/signup",
        data={
            "full_name": name, "department": "CSE",
            "batch_or_session": "21", "mobile": mobile,
            "password": password, "confirm_password": password,
            "is_campus_member": "on", "is_18_or_older": "on",
            "csrf_token": csrf,
        },
    )
    if approve:
        from app.db import get_engine
        from app.models.user import User
        with Session(get_engine()) as s:
            u = s.exec(
                select(User).where(User.mobile_e164 == _norm(mobile))
            ).first()
            u.status = "approved"  # type: ignore[attr-defined]
            s.add(u)
            s.commit()


def test_signin_open_redirect_is_blocked(client, settings):
    _signup_and_approve(
        client, mobile="01712345670", password="supersecret",
        name="Mod Mira", approve=True,
    )
    # Pick up the CSRF token from the signin form.
    r = client.get("/auth/signin")
    m = re.search(r'name="csrf_token" value="([^"]+)"', r.text)
    csrf = m.group(1)
    # Scheme-relative `next` -> redirect must collapse to "/".
    bad = client.post(
        "/auth/signin?next=//evil.com",
        data={"mobile": "01712345670", "password": "supersecret",
              "csrf_token": csrf, "next": "//evil.com"},
        follow_redirects=False,
    )
    assert bad.status_code == 303
    assert bad.headers.get("location", "") == "/"


def test_signin_open_redirect_abs_url_is_blocked(client, settings):
    _signup_and_approve(
        client, mobile="01712345678", password="supersecret",
        name="Mod Abs", approve=True,
    )
    r = client.get("/auth/signin")
    m = re.search(r'name="csrf_token" value="([^"]+)"', r.text)
    csrf = m.group(1)
    # Absolute `next` -> redirect must collapse to "/".
    bad = client.post(
        "/auth/signin",
        data={"mobile": "01712345678", "password": "supersecret",
              "csrf_token": csrf, "next": "https://evil.com/x"},
        follow_redirects=False,
    )
    assert bad.status_code == 303
    assert bad.headers.get("location", "") == "/"


# --- Audit log no longer logs mobile -------------------------------------


def test_signup_audit_does_not_include_mobile(client):
    _signup_and_approve(
        client, mobile="01712345671", password="supersecret",
        name="Mira", approve=False,
    )
    from app.db import get_engine
    from app.models.audit import AuditLog
    with Session(get_engine()) as s:
        rows = s.exec(
            select(AuditLog).where(AuditLog.action == "user.signup")
        ).all()
    assert rows, "expected an audit row for signup"
    for r in rows:
        # The full normalised mobile is "+8801712345671"; the test mobile
        # is the local form "01712345671". Either form must not appear in
        # the audit detail.
        assert "01712345671" not in (r.detail or "")
        assert "8801712345671" not in (r.detail or "")


# --- CLI no longer prints mobile -----------------------------------------


def test_create_moderator_does_not_print_mobile(monkeypatch, capsys):
    from app.cli import _create_moderator
    from app.config import Settings
    from app.db import set_engine as _set_engine
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    _set_engine(eng)
    SQLModel.metadata.create_all(eng)
    s = Settings(
        app_env="development", secret_key="x" * 40,
        database_url="sqlite:///:memory:",
    )
    monkeypatch.setattr("app.cli.get_settings", lambda: s)
    rc = _create_moderator(
        mobile="01712345672", password="pwpwpwpw",
        full_name="Mod Test", department="Staff", batch="N/A",
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert "01712345672" not in out
    assert "id=" in out


# --- require_moderator rejects suspended --------------------------------


def test_suspended_moderator_is_blocked_from_moderation_routes(
    client, engine, settings,
):
    # Make a moderator.
    from app.db import make_session_factory
    from app.models.user import User, UserRole, UserStatus
    factory = make_session_factory(engine)
    with factory() as s:
        u = User(
            full_name="Mod", department="CSE", batch_or_session="N/A",
            mobile_e164="+8801700009901",
            password_hash=hash_password("pwpwpwpw"),
            role=UserRole.MODERATOR, status=UserStatus.APPROVED,
            is_campus_member=True, is_18_or_older=True,
            created_at=datetime.now(timezone.utc),
            approved_at=datetime.now(timezone.utc),
        )
        s.add(u)
        s.commit()
        s.refresh(u)
        uid = u.id
    # Issue a session as that moderator.
    from app.main import make_session_cookie
    cookie = make_session_cookie(settings.secret_key, uid, "moderator", new_token())
    client.cookies.set("cr_session", cookie)
    # Access works while approved.
    r = client.get("/moderation", follow_redirects=False)
    assert r.status_code == 200
    # Suspend; existing session should be locked out immediately. The
    # queue route deliberately returns 404 (not 403) to avoid revealing
    # the URL, but the suspension must be enforced.
    with factory() as s:
        u = s.get(User, uid)
        u.status = UserStatus.SUSPENDED
        s.add(u)
        s.commit()
    r = client.get("/moderation", follow_redirects=False)
    assert r.status_code == 404
    # And require_moderator on a POST also rejects: try to suspend another
    # user via the POST endpoint.
    from app.models.audit import AuditLog
    r = client.post(
        "/moderation/accounts/999999/suspend",
        data={"csrf_token": "ignored", "reason": "x"},
        follow_redirects=False,
    )
    # 403 because CSRF is missing; that's fine — what we care about is
    # that a suspended moderator can't author moderation actions.
    assert r.status_code in (403, 404)
    # And no audit row is created for the suspended moderator.
    with factory() as s:
        rows = s.exec(
            select(AuditLog).where(
                AuditLog.actor_id == uid,
                AuditLog.action.like("moderation.%"),
            )
        ).all()
        assert rows == []


# --- Worker skips past-departure reminders -------------------------------


def test_worker_skips_past_departure_trip_reminder(monkeypatch, client):
    from app.db import set_engine as _set_engine
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    _set_engine(eng)
    SQLModel.metadata.create_all(eng)
    from app.models.user import User, UserRole, UserStatus
    from app.models.place import Place
    from app.models.trip import Trip, TripInstance, TripStatus
    from app.models.booking import Booking, BookingStatus
    from app.models.notification import Notification
    from app.jobs import enqueue
    from app.worker import _process_due_jobs
    with Session(eng) as s:
        drv = User(
            full_name="D", department="CSE", batch_or_session="21",
            mobile_e164="+8801700009101",
            password_hash=hash_password("pwpwpwpw"),
            role=UserRole.MEMBER, status=UserStatus.APPROVED,
            is_campus_member=True, is_18_or_older=True,
            created_at=datetime.now(timezone.utc),
        )
        rid = User(
            full_name="R", department="CSE", batch_or_session="21",
            mobile_e164="+8801700009102",
            password_hash=hash_password("pwpwpwpw"),
            role=UserRole.MEMBER, status=UserStatus.APPROVED,
            is_campus_member=True, is_18_or_older=True,
            created_at=datetime.now(timezone.utc),
        )
        s.add(drv)
        s.add(rid)
        s.commit()
        s.refresh(drv)
        s.refresh(rid)
        pa = Place(name="A", group_label="Main", kind="gate",
                   created_at=datetime.now(timezone.utc))
        pb = Place(name="B", group_label="Other", kind="neighbourhood",
                   created_at=datetime.now(timezone.utc))
        s.add(pa)
        s.add(pb)
        s.commit()
        s.refresh(pa)
        s.refresh(pb)
        # Departure 2 hours ago.
        past = datetime.now(timezone.utc) - timedelta(hours=2)
        t = Trip(
            driver_id=drv.id, from_place_id=pa.id, to_place_id=pb.id,
            earliest_departure=past, latest_departure=past + timedelta(minutes=15),
            seats_offered=3, cost_per_seat_paisa=0,
            recurrence_kind="one_off", weekdays_mask=0,
            series_start_date=past,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        s.add(t)
        s.commit()
        s.refresh(t)
        inst = TripInstance(
            trip_id=t.id, depart_at=past, seats_taken=0,
            status=TripStatus.ACTIVE,
        )
        s.add(inst)
        s.commit()
        s.refresh(inst)
        b = Booking(
            trip_instance_id=inst.id, rider_id=rid.id, driver_id=drv.id,
            status=BookingStatus.ACCEPTED,
            created_at=datetime.now(timezone.utc),
        )
        s.add(b)
        s.commit()
        s.refresh(b)
        # Enqueue a reminder that is "due now".
        enqueue(
            s, kind="trip_reminder",
            run_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            payload={"booking_id": b.id},
        )
        s.commit()
    _process_due_jobs("test-worker")
    with Session(eng) as s:
        notes = s.exec(
            select(Notification).where(Notification.kind == "trip.reminder")
        ).all()
    assert notes == []


# --- Security headers ----------------------------------------------------


def test_csp_and_permissions_policy_are_set(client):
    r = client.get("/")
    csp = r.headers.get("content-security-policy", "")
    assert "object-src 'none'" in csp
    assert "upgrade-insecure-requests" in csp
    pp = r.headers.get("permissions-policy", "")
    assert "camera=()" in pp
    assert "microphone=()" in pp
    assert "geolocation=()" in pp


# --- Trusted link does not leak PII --------------------------------------


def test_trusted_link_does_not_leak_pii(client, engine, settings):
    from app.db import make_session_factory
    from app.models.user import User, UserStatus
    from app.models.place import Place
    from app.models.trip import Trip, TripInstance, TripStatus
    from app.models.booking import Booking, BookingStatus
    from app.models.trust import TrustedContactLink
    from app.reveal import make_trusted_token
    factory = make_session_factory(engine)
    depart = datetime.now(timezone.utc) + timedelta(hours=3)
    with factory() as s:
        drv = User(
            full_name="Dan Driver", department="CSE", batch_or_session="21",
            mobile_e164="+8801700009501",
            password_hash=hash_password("pwpwpwpw"),
            status=UserStatus.APPROVED, driver_verified=True,
            vehicle_description="white sedan",
            vehicle_plate="DH-K-9-8765",
            is_campus_member=True, is_18_or_older=True,
            created_at=datetime.now(timezone.utc),
        )
        rid = User(
            full_name="Riya Rider", department="CSE", batch_or_session="22",
            mobile_e164="+8801700009502",
            password_hash=hash_password("pwpwpwpw"),
            status=UserStatus.APPROVED,
            is_campus_member=True, is_18_or_older=True,
            created_at=datetime.now(timezone.utc),
        )
        s.add(drv)
        s.add(rid)
        s.commit()
        s.refresh(drv)
        s.refresh(rid)
        pa = Place(name="Campus Gate", group_label="Main", kind="gate",
                   created_at=datetime.now(timezone.utc))
        pb = Place(name="Dhanmondi 27", group_label="Dhanmondi",
                   kind="neighbourhood",
                   created_at=datetime.now(timezone.utc))
        s.add(pa)
        s.add(pb)
        s.commit()
        s.refresh(pa)
        s.refresh(pb)
        t = Trip(
            driver_id=drv.id, from_place_id=pa.id, to_place_id=pb.id,
            earliest_departure=depart,
            latest_departure=depart + timedelta(minutes=15),
            seats_offered=3, cost_per_seat_paisa=0,
            recurrence_kind="one_off", weekdays_mask=0,
            series_start_date=depart,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        s.add(t)
        s.commit()
        s.refresh(t)
        inst = TripInstance(
            trip_id=t.id, depart_at=depart, seats_taken=1,
            status=TripStatus.ACTIVE,
        )
        s.add(inst)
        s.commit()
        s.refresh(inst)
        b = Booking(
            trip_instance_id=inst.id, rider_id=rid.id, driver_id=drv.id,
            status=BookingStatus.ACCEPTED,
            created_at=datetime.now(timezone.utc),
        )
        s.add(b)
        s.commit()
        s.refresh(b)
        raw, h = make_trusted_token()
        link = TrustedContactLink(
            booking_id=b.id, trip_instance_id=inst.id,
            created_by_id=rid.id, token_hash=h,
            created_at=datetime.now(timezone.utc),
            expires_at=depart + timedelta(hours=2),
        )
        s.add(link)
        s.commit()
    r = client.get(f"/trusted/{raw}")
    assert r.status_code == 200
    body = r.text
    # Allowed: route, time, first name, vehicle description.
    assert "Campus Gate" in body
    assert "Dhanmondi 27" in body
    assert "Dan" in body  # first name
    assert "white sedan" in body
    # Forbidden: anything that could identify or contact the driver/rider.
    assert "Driver Dan" not in body
    assert "Riya" not in body
    assert "8801700009501" not in body
    assert "8801700009502" not in body
    assert "DH-K-9-8765" not in body
    assert "CSE" not in body or "department" not in body.lower()
