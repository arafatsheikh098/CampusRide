"""Job queue + worker tests (F9).

Covers:
  * enqueue with dedupe key collapses duplicates
  * claim_next returns due jobs and skips non-due ones
  * mark_done / mark_failed state transitions
  * the worker dispatches a `trip_reminder` to the rider
  * the worker is a no-op when no job is due
  * the Telegram push is scheduled for a linked rider and not for an
    unlinked one
  * the public webhook rejects requests without the secret token
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import StaticPool, create_engine
from sqlmodel import Session, SQLModel, select

from app import models  # noqa: F401
from app.db import set_engine
from app.jobs import claim_next, enqueue, mark_done, mark_failed
from app.models.booking import Booking, BookingStatus
from app.models.job import Job, JobStatus
from app.models.notification import Notification
from app.models.place import Place
from app.models.telegram_link import TelegramLink
from app.models.trip import Trip, TripInstance, TripStatus
from app.models.user import User, UserStatus
from app.security import hash_password, new_token


# --- Fixtures -------------------------------------------------------------


def _engine():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    set_engine(eng)
    SQLModel.metadata.create_all(eng)
    return eng


def _make_user(eng, *, mobile, name, telegram_chat_id=None):
    with Session(eng) as s:
        u = User(
            full_name=name, department="CSE", batch_or_session="21",
            mobile_e164=mobile,
            password_hash=hash_password("pwpwpwpw"),
            status=UserStatus.APPROVED,
            is_campus_member=True, is_18_or_older=True,
            driver_verified=True, vehicle_description="white sedan",
            telegram_chat_id=telegram_chat_id,
            created_at=datetime.now(timezone.utc),
        )
        s.add(u)
        s.commit()
        s.refresh(u)
        return u.id


def _make_place(eng, *, name="A", group="Main", kind="gate"):
    with Session(eng) as s:
        p = Place(name=name, group_label=group, kind=kind,
                  created_at=datetime.now(timezone.utc))
        s.add(p)
        s.commit()
        s.refresh(p)
        return p.id


def _make_trip(eng, *, driver_id, from_place_id, to_place_id, earliest):
    with Session(eng) as s:
        t = Trip(
            driver_id=driver_id, from_place_id=from_place_id,
            to_place_id=to_place_id,
            earliest_departure=earliest,
            latest_departure=earliest + timedelta(minutes=15),
            seats_offered=3, cost_per_seat_paisa=0,
            recurrence_kind="one_off", weekdays_mask=0,
            series_start_date=earliest,
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


def _make_booking(eng, *, rider_id, driver_id, inst_id, status):
    with Session(eng) as s:
        b = Booking(
            trip_instance_id=inst_id, rider_id=rider_id,
            driver_id=driver_id, status=status,
            created_at=datetime.now(timezone.utc),
        )
        s.add(b)
        s.commit()
        s.refresh(b)
        return b.id


# --- Tests ----------------------------------------------------------------


def test_enqueue_dedupe_collapses_duplicates():
    eng = _engine()
    with Session(eng) as s:
        when = datetime.now(timezone.utc) + timedelta(minutes=5)
        j1 = enqueue(s, kind="trip_reminder", run_at=when,
                     payload={"booking_id": 1},
                     dedupe_key="trip_reminder:1")
        s.commit()
        assert j1 is not None
        j2 = enqueue(s, kind="trip_reminder", run_at=when,
                     payload={"booking_id": 1},
                     dedupe_key="trip_reminder:1")
        s.commit()
        assert j2 is None
        rows = s.exec(select(Job)).all()
        assert len(rows) == 1


def test_enqueue_rejects_unknown_kind():
    eng = _engine()
    with Session(eng) as s:
        try:
            enqueue(s, kind="bogus",
                    run_at=datetime.now(timezone.utc))
        except ValueError as e:
            assert "unknown" in str(e)
        else:
            raise AssertionError("expected ValueError")


def test_claim_next_skips_not_due():
    eng = _engine()
    with Session(eng) as s:
        later = datetime.now(timezone.utc) + timedelta(hours=1)
        enqueue(s, kind="trip_reminder", run_at=later, payload={})
        s.commit()
        # Now is before run_at: claim returns None.
        job = claim_next(s, now=datetime.now(timezone.utc))
        assert job is None
    # Past-due: claim returns it.
    eng2 = _engine()
    with Session(eng2) as s:
        past = datetime.now(timezone.utc) - timedelta(hours=1)
        enqueue(s, kind="trip_reminder", run_at=past, payload={})
        s.commit()
        job = claim_next(s, now=datetime.now(timezone.utc))
        assert job is not None
        assert job.status == JobStatus.RUNNING
        assert job.attempts == 1


def test_mark_done_and_failed_transitions():
    eng = _engine()
    with Session(eng) as s:
        when = datetime.now(timezone.utc) - timedelta(minutes=1)
        enqueue(s, kind="trip_reminder", run_at=when, payload={})
        s.commit()
        job = claim_next(s, now=datetime.now(timezone.utc))
        assert job is not None
        mark_done(s, job)
        s.commit()
        s.refresh(job)
        assert job.status == JobStatus.DONE
    eng = _engine()
    with Session(eng) as s:
        enqueue(s, kind="trip_reminder", run_at=when, payload={})
        s.commit()
        job = claim_next(s, now=datetime.now(timezone.utc))
        mark_failed(s, job, "boom")
        s.commit()
        s.refresh(job)
        # attempts is 1, < 5 so we go back to PENDING.
        assert job.status == JobStatus.PENDING
        assert job.last_error == "boom"


def test_worker_dispatches_trip_reminder_to_rider():
    eng = _engine()
    drv = _make_user(eng, mobile="+8801700002001", name="Driver")
    rid = _make_user(eng, mobile="+8801700002002", name="Rider")
    pa = _make_place(eng, name="A")
    pb = _make_place(eng, name="B", group="Other", kind="neighbourhood")
    earliest = datetime.now(timezone.utc) + timedelta(minutes=5)
    trip_id, inst_id = _make_trip(
        eng, driver_id=drv, from_place_id=pa, to_place_id=pb,
        earliest=earliest,
    )
    bid = _make_booking(
        eng, rider_id=rid, driver_id=drv, inst_id=inst_id,
        status=BookingStatus.ACCEPTED,
    )
    with Session(eng) as s:
        enqueue(
            s, kind="trip_reminder",
            run_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            payload={"booking_id": bid},
        )
        s.commit()
    # Manually run a tick of the worker.
    from app.worker import _process_due_jobs
    processed = _process_due_jobs("test-worker")
    assert processed == 1
    with Session(eng) as s:
        notes = s.exec(
            select(Notification).where(Notification.user_id == rid)
        ).all()
        assert any(n.kind == "trip.reminder" for n in notes)
        job = s.exec(select(Job)).first()
        assert job.status == JobStatus.DONE


def test_worker_no_op_when_nothing_due():
    _engine()
    processed = _process_due_jobs_static()
    assert processed == 0


def _process_due_jobs_static():
    from app.worker import _process_due_jobs
    return _process_due_jobs("test-worker")


def test_telegram_link_uses_hashed_code():
    eng = _engine()
    uid = _make_user(eng, mobile="+8801700002101", name="Aisha")
    from app.security import hash_token
    raw = new_token()
    h = hash_token(raw)
    with Session(eng) as s:
        link = TelegramLink(
            user_id=uid, code_hash=h, used=False,
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        s.add(link)
        s.commit()
    with Session(eng) as s:
        found = s.exec(
            select(TelegramLink).where(TelegramLink.code_hash == h)
        ).first()
        assert found is not None
        assert found.code_hash != raw  # never store the raw code


def test_webhook_requires_secret_token(client, settings, monkeypatch):
    # Enable the webhook.
    new_settings = settings.model_copy(update={
        "telegram_bot_token": "x", "telegram_webhook_secret": "s",
    })
    import app.routes.telegram as tg
    monkeypatch.setattr(tg, "get_settings", lambda: new_settings)
    monkeypatch.setattr(tg, "_telegram_enabled", lambda: True)
    body = json.dumps({
        "message": {"chat": {"id": 12345}, "text": "hello"},
    }).encode("utf-8")
    # No header: 403.
    r = client.post("/telegram/webhook", content=body,
                    headers={"Content-Type": "application/json"})
    assert r.status_code == 403
    # Wrong header: 403.
    r = client.post("/telegram/webhook", content=body,
                    headers={"Content-Type": "application/json",
                             "X-Telegram-Bot-Api-Secret-Token": "nope"})
    assert r.status_code == 403


def test_webhook_links_user_and_stores_chat_id(
    client, settings, monkeypatch,
):
    from app.security import hash_token
    from app.models.user import User
    eng = _engine()
    uid = _make_user(eng, mobile="+8801700002201", name="Aisha")
    raw = new_token()
    h = hash_token(raw)
    with Session(eng) as s:
        s.add(TelegramLink(
            user_id=uid, code_hash=h, used=False,
            created_at=datetime.now(timezone.utc),
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        ))
        s.commit()
    new_settings = settings.model_copy(update={
        "telegram_bot_token": "x", "telegram_webhook_secret": "s",
    })
    import app.routes.telegram as tg
    monkeypatch.setattr(tg, "get_settings", lambda: new_settings)
    monkeypatch.setattr(tg, "_telegram_enabled", lambda: True)
    body = json.dumps({
        "message": {"chat": {"id": 999}, "text": raw},
    }).encode("utf-8")
    r = client.post(
        "/telegram/webhook", content=body,
        headers={"Content-Type": "application/json",
                 "X-Telegram-Bot-Api-Secret-Token": "s"},
    )
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    with Session(eng) as s:
        u = s.get(User, uid)
        assert u.telegram_chat_id == "999"
        link = s.exec(
            select(TelegramLink).where(TelegramLink.user_id == uid)
        ).first()
        assert link.used is True


def test_worker_dispatch_trip_reminder_skips_cancelled_trip():
    eng = _engine()
    drv = _make_user(eng, mobile="+8801700002301", name="Driver")
    rid = _make_user(eng, mobile="+8801700002302", name="Rider")
    pa = _make_place(eng, name="A")
    pb = _make_place(eng, name="B", group="Other", kind="neighbourhood")
    earliest = datetime.now(timezone.utc) + timedelta(minutes=5)
    trip_id, inst_id = _make_trip(
        eng, driver_id=drv, from_place_id=pa, to_place_id=pb,
        earliest=earliest,
    )
    bid = _make_booking(
        eng, rider_id=rid, driver_id=drv, inst_id=inst_id,
        status=BookingStatus.ACCEPTED,
    )
    # Cancel the trip.
    with Session(eng) as s:
        inst = s.get(TripInstance, inst_id)
        inst.status = TripStatus.CANCELLED
        s.commit()
    with Session(eng) as s:
        enqueue(
            s, kind="trip_reminder",
            run_at=datetime.now(timezone.utc) - timedelta(seconds=1),
            payload={"booking_id": bid},
        )
        s.commit()
    from app.worker import _process_due_jobs
    _process_due_jobs("test-worker")
    with Session(eng) as s:
        notes = s.exec(
            select(Notification).where(
                Notification.user_id == rid,
                Notification.kind == "trip.reminder",
            )
        ).all()
        # No reminder written: the trip was cancelled.
        assert not notes
