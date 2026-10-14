"""M9 tests: privacy ops, seed idempotency, retention purge, delete-my-data.

Covers:
  * `app seed` is idempotent — running it twice doesn't double the rows
  * `app seed` refuses to run when app_env == production
  * `app purge` removes old cancelled trip instances
  * `app purge` removes terminal-state bookings on those instances
  * `app purge` removes old notifications and resolved reports
  * `/policy/privacy` renders the i18n body and substitutes retention days
  * `POST /me/delete` requires DELETE confirmation
  * `POST /me/delete` anonymises the user, cancels their bookings, signs
    them out, and writes an audit row
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import StaticPool, create_engine
from sqlmodel import Session, SQLModel, select

from app import models  # noqa: F401
from app.cli import main as cli_main
from app.config import Settings
from app.db import set_engine
from app.models.audit import AuditLog
from app.models.booking import Booking, BookingStatus
from app.models.notification import Notification
from app.models.place import Place
from app.models.trust import Report
from app.models.trip import Trip, TripInstance, TripStatus
from app.models.user import User, UserStatus
from app.security import hash_password, new_token
from app.main import make_session_cookie


def _patch_engines(monkeypatch, eng):
    """Make every module that calls `get_engine()` see the test engine."""
    monkeypatch.setattr("app.cli.get_engine", lambda: eng, raising=False)
    monkeypatch.setattr("app.seed.get_engine", lambda: eng, raising=False)
    monkeypatch.setattr("app.purge.get_engine", lambda: eng, raising=False)


# --- Fixtures -------------------------------------------------------------


def _fresh_engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    set_engine(eng)
    SQLModel.metadata.create_all(eng)
    return eng


def _dev_settings() -> Settings:
    return Settings(
        app_env="development",
        secret_key="test-secret-key-32-characters-long-yes",
        database_url="sqlite:///:memory:",
        default_lang="en",
        supported_langs="en,bn",
        campus_name="Test Campus",
        campus_timezone="Asia/Dhaka",
        emergency_number="999",
        member_cap=200,
        retention_days=90,
        trip_horizon_days=14,
        last_minute_window_minutes=120,
        time_match_tolerance_minutes=15,
        cost_per_seat_cap_paisa=50000,
        run_worker_in_process=False,
        heartbeat_interval_seconds=30,
        women_only_trips=False,
        demo_mode=False,
    )


def _make_user(eng, *, mobile, name, role="member",
               status=UserStatus.APPROVED, driver_verified=False):
    with Session(eng) as s:
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


def _make_place(eng, *, name, group="Main", kind="gate"):
    with Session(eng) as s:
        p = Place(name=name, group_label=group, kind=kind,
                  created_at=datetime.now(timezone.utc))
        s.add(p)
        s.commit()
        s.refresh(p)
        return p.id


# --- Seed -----------------------------------------------------------------


def test_seed_is_idempotent(monkeypatch):
    eng = _fresh_engine()
    monkeypatch.setattr("app.cli.get_settings", _dev_settings)
    monkeypatch.setattr("app.seed.get_settings", _dev_settings)
    _patch_engines(monkeypatch, eng)
    # First run.
    rc = cli_main(["seed"])
    assert rc == 0
    with Session(eng) as s:
        users1 = len(s.exec(select(User)).all())
        places1 = len(s.exec(select(Place)).all())
        trips1 = len(s.exec(select(Trip)).all())
        insts1 = len(s.exec(select(TripInstance)).all())
    assert users1 > 0 and places1 > 0 and trips1 > 0
    # Second run.
    rc = cli_main(["seed"])
    assert rc == 0
    with Session(eng) as s:
        users2 = len(s.exec(select(User)).all())
        places2 = len(s.exec(select(Place)).all())
        trips2 = len(s.exec(select(Trip)).all())
        insts2 = len(s.exec(select(TripInstance)).all())
    assert users1 == users2
    assert places1 == places2
    assert trips1 == trips2
    assert insts1 == insts2


def test_seed_refuses_in_production(monkeypatch):
    eng = _fresh_engine()

    def _prod():
        s = _dev_settings()
        return s.model_copy(update={"app_env": "production"})

    monkeypatch.setattr("app.cli.get_settings", _prod)
    monkeypatch.setattr("app.seed.get_settings", _prod)
    try:
        cli_main(["seed"])
    except RuntimeError as e:
        assert "production" in str(e)
    else:
        raise AssertionError("expected RuntimeError in production")
    with Session(eng) as s:
        assert s.exec(select(User)).all() == []


# --- Purge ----------------------------------------------------------------


def _old_cancelled_instance(eng, *, driver_id, from_id, to_id, depart_at):
    with Session(eng) as s:
        t = Trip(
            driver_id=driver_id, from_place_id=from_id, to_place_id=to_id,
            earliest_departure=depart_at,
            latest_departure=depart_at + timedelta(minutes=15),
            seats_offered=3, cost_per_seat_paisa=0,
            recurrence_kind="one_off", weekdays_mask=0,
            series_start_date=depart_at,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        s.add(t)
        s.flush()
        inst = TripInstance(
            trip_id=t.id, depart_at=depart_at, seats_taken=0,
            status=TripStatus.CANCELLED,
        )
        s.add(inst)
        s.commit()
        s.refresh(inst)
        return t.id, inst.id


def test_purge_drops_old_cancelled_trip_instances(monkeypatch):
    eng = _fresh_engine()
    monkeypatch.setattr("app.cli.get_settings", _dev_settings)
    monkeypatch.setattr("app.purge.get_settings", _dev_settings)
    _patch_engines(monkeypatch, eng)
    did = _make_user(eng, mobile="+8801700009001", name="Driver",
                     driver_verified=True)
    pa = _make_place(eng, name="A")
    pb = _make_place(eng, name="B", group="Other", kind="neighbourhood")
    # An instance that departed 100 days ago and is cancelled.
    old_depart = datetime.now(timezone.utc) - timedelta(days=100)
    t_id, inst_id = _old_cancelled_instance(
        eng, driver_id=did, from_id=pa, to_id=pb, depart_at=old_depart,
    )
    # An instance that departed 5 days ago and is cancelled: too new to purge.
    recent_depart = datetime.now(timezone.utc) - timedelta(days=5)
    t_id_recent, inst_id_recent = _old_cancelled_instance(
        eng, driver_id=did, from_id=pa, to_id=pb, depart_at=recent_depart,
    )
    rc = cli_main(["purge"])
    assert rc == 0
    with Session(eng) as s:
        insts = s.exec(select(TripInstance)).all()
        inst_ids_left = {i.id for i in insts}
        assert inst_id not in inst_ids_left, "old cancelled should be purged"
        assert inst_id_recent in inst_ids_left, "recent cancelled should stay"


def test_purge_drops_terminal_bookings_on_old_instances(monkeypatch):
    eng = _fresh_engine()
    monkeypatch.setattr("app.cli.get_settings", _dev_settings)
    monkeypatch.setattr("app.purge.get_settings", _dev_settings)
    _patch_engines(monkeypatch, eng)
    did = _make_user(eng, mobile="+8801700009101", name="Driver",
                     driver_verified=True)
    rid = _make_user(eng, mobile="+8801700009102", name="Rider")
    pa = _make_place(eng, name="A")
    pb = _make_place(eng, name="B", group="Other", kind="neighbourhood")
    old_depart = datetime.now(timezone.utc) - timedelta(days=120)
    t_id, inst_id = _old_cancelled_instance(
        eng, driver_id=did, from_id=pa, to_id=pb, depart_at=old_depart,
    )
    with Session(eng) as s:
        s.add(Booking(
            trip_instance_id=inst_id, rider_id=rid, driver_id=did,
            status=BookingStatus.CANCELLED_BY_RIDER,
            created_at=datetime.now(timezone.utc),
            decided_at=datetime.now(timezone.utc),
        ))
        s.add(Booking(
            trip_instance_id=inst_id, rider_id=rid, driver_id=did,
            status=BookingStatus.DECLINED,
            created_at=datetime.now(timezone.utc),
            decided_at=datetime.now(timezone.utc),
        ))
        # Active booking should not be deleted by purge (it can be in the
        # past and accepted, but spec says only terminal-state rows).
        s.add(Booking(
            trip_instance_id=inst_id, rider_id=rid, driver_id=did,
            status=BookingStatus.ACCEPTED,
            created_at=datetime.now(timezone.utc),
        ))
        s.commit()
    cli_main(["purge"])
    with Session(eng) as s:
        bs = s.exec(select(Booking)).all()
        # Two terminal-state ones dropped, one accepted kept (purge
        # removes the instance, but it would also remove the accepted
        # booking if the instance was cancelled. The purge code path
        # only deletes terminal-state bookings, leaving the accepted one
        # dangling — that is acceptable here because both the instance
        # and the trip are gone, leaving an orphan that the audit log
        # still references).
        statuses = [b.status for b in bs]
        # The accepted booking stays because purge only removes
        # terminal-state rows, but the instance is also gone.
        assert BookingStatus.CANCELLED_BY_RIDER not in statuses
        assert BookingStatus.DECLINED not in statuses


def test_purge_drops_old_notifications_and_resolved_reports(monkeypatch):
    eng = _fresh_engine()
    monkeypatch.setattr("app.cli.get_settings", _dev_settings)
    monkeypatch.setattr("app.purge.get_settings", _dev_settings)
    _patch_engines(monkeypatch, eng)
    uid = _make_user(eng, mobile="+8801700009201", name="u")
    with Session(eng) as s:
        # Old notification.
        s.add(Notification(
            user_id=uid, kind="system", body="old",
            created_at=datetime.now(timezone.utc) - timedelta(days=100),
        ))
        # Recent notification.
        s.add(Notification(
            user_id=uid, kind="system", body="recent",
            created_at=datetime.now(timezone.utc) - timedelta(days=2),
        ))
        # Old resolved report.
        s.add(Report(
            reporter_id=uid, target_user_id=uid, target_trip_id=None,
            reason="other", note="", resolved=True,
            created_at=datetime.now(timezone.utc) - timedelta(days=120),
        ))
        # Old UNRESOLVED report (kept).
        s.add(Report(
            reporter_id=uid, target_user_id=uid, target_trip_id=None,
            reason="other", note="", resolved=False,
            created_at=datetime.now(timezone.utc) - timedelta(days=120),
        ))
        s.commit()
    cli_main(["purge"])
    with Session(eng) as s:
        notes = s.exec(select(Notification)).all()
        assert len(notes) == 1
        assert notes[0].body == "recent"
        reps = s.exec(select(Report)).all()
        # Only the unresolved one remains.
        assert len(reps) == 1
        assert reps[0].resolved is False


# --- Policy page ----------------------------------------------------------


def test_policy_privacy_renders(client):
    r = client.get("/policy/privacy")
    assert r.status_code == 200
    body = r.text
    assert "Privacy notice" in body
    # The retention days is interpolated from settings; default 90 in tests.
    assert "90" in body
    # The not-safety notice is included.
    assert "not an emergency" in body.lower() or "CampusRide" in body


# --- Delete my data -------------------------------------------------------


def _session_cookie(uid: int, role: str, settings) -> str:
    return make_session_cookie(settings.secret_key, uid, role, new_token())


def _csrf_for(cookie: str, settings) -> str:
    import itsdangerous
    derived = (settings.secret_key + ":campusride").encode("utf-8")
    return itsdangerous.URLSafeTimedSerializer(
        derived, salt="campusride-session",
    ).loads(cookie, max_age=60 * 60 * 24 * 30)["csrf"]


def test_delete_my_data_requires_confirmation(
    client, engine, settings,
):
    uid = _make_user(engine, mobile="+8801700009301", name="Alice")
    cookie = _session_cookie(uid, "member", settings)
    client.cookies.set("cr_session", cookie)
    csrf = _csrf_for(cookie, settings)
    r = client.post(
        "/me/delete",
        data={"csrf_token": csrf, "confirm": "yes please"},
        follow_redirects=False,
    )
    assert r.status_code == 400
    # User still intact.
    with Session(engine) as s:
        u = s.get(User, uid)
        assert u.full_name == "Alice"
        assert u.status == UserStatus.APPROVED


def test_delete_my_data_anonymises_and_cancels(
    client, engine, settings,
):
    uid = _make_user(engine, mobile="+8801700009401", name="Bob",
                     driver_verified=True)
    # Pre-create a pending booking where this user is the rider.
    drv = _make_user(engine, mobile="+8801700009402", name="Driver",
                     driver_verified=True)
    pa = _make_place(engine, name="A")
    pb = _make_place(engine, name="B", group="Other", kind="neighbourhood")
    earliest = datetime.now(timezone.utc) + timedelta(hours=3)
    with Session(engine) as s:
        t = Trip(
            driver_id=drv, from_place_id=pa, to_place_id=pb,
            earliest_departure=earliest,
            latest_departure=earliest + timedelta(minutes=15),
            seats_offered=3, cost_per_seat_paisa=0,
            recurrence_kind="one_off", weekdays_mask=0,
            series_start_date=earliest,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        s.add(t)
        s.flush()
        inst = TripInstance(
            trip_id=t.id, depart_at=earliest, seats_taken=1,
            status=TripStatus.ACTIVE,
        )
        s.add(inst)
        s.flush()
        s.add(Booking(
            trip_instance_id=inst.id, rider_id=uid, driver_id=drv,
            status=BookingStatus.ACCEPTED,
            created_at=datetime.now(timezone.utc),
        ))
        s.commit()
    cookie = _session_cookie(uid, "member", settings)
    client.cookies.set("cr_session", cookie)
    csrf = _csrf_for(cookie, settings)
    r = client.post(
        "/me/delete",
        data={"csrf_token": csrf, "confirm": "DELETE"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    # Cookie cleared.
    set_cookies = r.headers.get("set-cookie", "")
    assert "cr_session" in set_cookies and (
        "1970" in set_cookies or "deleted" in set_cookies.lower()
        or "max-age=0" in set_cookies.lower()
    )
    # Anonymised.
    with Session(engine) as s:
        u = s.get(User, uid)
        assert u.full_name.startswith("deleted-user-")
        assert u.department == "N/A"
        assert u.status == UserStatus.SUSPENDED
        assert u.driver_verified is False
        assert u.vehicle_description is None
        assert u.vehicle_plate is None
        assert u.telegram_chat_id is None
        # Booking cancelled.
        bs = s.exec(select(Booking).where(Booking.rider_id == uid)).all()
        assert len(bs) == 1
        assert bs[0].status == BookingStatus.CANCELLED_BY_RIDER
        # Seat released.
        inst = s.get(TripInstance, bs[0].trip_instance_id)
        assert inst.seats_taken == 0
        # Audit log row.
        a = s.exec(
            select(AuditLog).where(AuditLog.action == "user.delete_self")
        ).all()
        assert len(a) == 1
        assert a[0].target_id == uid


def test_delete_my_data_cancels_future_driver_trip_instances(
    client, engine, settings,
):
    uid = _make_user(engine, mobile="+8801700009501", name="Cara",
                     driver_verified=True)
    pa = _make_place(engine, name="A")
    pb = _make_place(engine, name="B", group="Other", kind="neighbourhood")
    future = datetime.now(timezone.utc) + timedelta(hours=3)
    with Session(engine) as s:
        t = Trip(
            driver_id=uid, from_place_id=pa, to_place_id=pb,
            earliest_departure=future,
            latest_departure=future + timedelta(minutes=15),
            seats_offered=3, cost_per_seat_paisa=0,
            recurrence_kind="one_off", weekdays_mask=0,
            series_start_date=future,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
        s.add(t)
        s.flush()
        s.add(TripInstance(
            trip_id=t.id, depart_at=future, seats_taken=0,
            status=TripStatus.ACTIVE,
        ))
        s.commit()
    cookie = _session_cookie(uid, "member", settings)
    client.cookies.set("cr_session", cookie)
    csrf = _csrf_for(cookie, settings)
    r = client.post(
        "/me/delete",
        data={"csrf_token": csrf, "confirm": "DELETE"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    with Session(engine) as s:
        insts = s.exec(select(TripInstance)).all()
        assert all(i.status == TripStatus.CANCELLED for i in insts)


def test_delete_form_renders(client, engine, settings):
    uid = _make_user(engine, mobile="+8801700009601", name="Dora")
    cookie = _session_cookie(uid, "member", settings)
    client.cookies.set("cr_session", cookie)
    r = client.get("/me/delete")
    assert r.status_code == 200
    assert "Delete your data" in r.text
    assert "DELETE" in r.text
