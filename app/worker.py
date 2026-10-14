"""Worker entry point and dispatch loop (F9).

The worker does three things on each tick:
  1. Update the heartbeat row (powers `/health`).
  2. Claim the next due job from the queue.
  3. Dispatch by `kind`.

Kinds:
  * `trip_reminder`  — write an in-app notification to the rider ~1h
                       before departure.
  * `telegram_ping`  — push a plain-text Telegram message via the bot
                       API. The payload is already minimal: no names,
                       numbers or places beyond the departure time.

On Postgres, a session-level advisory lock keyed off the worker id
ensures only one worker dispatches at a time. On SQLite, a single
worker is the norm in dev/test; the application-level job-claim
transition inside its own transaction is sufficient.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import socket
import time
from datetime import datetime, timezone

from sqlalchemy import text
from sqlmodel import select

from .config import get_settings
from .db import get_engine, make_session_factory
from .jobs import claim_next, mark_done, mark_failed
from .models.heartbeat import Heartbeat
from .models.job import Job
from .security import assert_safe_secret_key

logger = logging.getLogger("campusride.worker")


def _worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


def _heartbeat(wid: str) -> None:
    eng = get_engine()
    factory = make_session_factory(eng)
    now = datetime.now(timezone.utc)
    with factory() as sess:
        row = sess.get(Heartbeat, wid)
        if row is None:
            row = Heartbeat(worker_id=wid, last_seen=now)
            sess.add(row)
        else:
            row.last_seen = now
        sess.commit()


def _try_advisory_lock(eng, key: int) -> bool:
    """Postgres only. Returns True if the lock was acquired."""
    try:
        with eng.connect() as conn:
            r = conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": key})
            row = r.first()
            return bool(row and row[0])
    except Exception:
        return False


def _release_advisory_lock(eng, key: int) -> None:
    try:
        with eng.connect() as conn:
            conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": key})
            conn.commit()
    except Exception:
        return


# --- Dispatchers ----------------------------------------------------------


def _dispatch_trip_reminder(payload: dict) -> None:
    """Write an in-app reminder to the rider. Skip if the trip is no
    longer active, the booking is no longer accepted, or the departure
    time is already in the past (a late reminder is confusing)."""
    from .models.booking import Booking, BookingStatus
    from .models.notification import Notification
    from .models.trip import TripInstance, TripStatus
    from .models.user import User

    bid = int(payload.get("booking_id") or 0)
    if not bid:
        return
    eng = get_engine()
    factory = make_session_factory(eng)
    now = datetime.now(timezone.utc)
    with factory() as sess:
        b = sess.get(Booking, bid)
        if b is None or b.status != BookingStatus.ACCEPTED:
            return
        inst = sess.get(TripInstance, b.trip_instance_id)
        if inst is None or inst.status != TripStatus.ACTIVE:
            return
        depart_at = inst.depart_at
        if depart_at.tzinfo is None:
            depart_at = depart_at.replace(tzinfo=timezone.utc)
        # Don't send a "departs at HH:MM" reminder for a trip that has
        # already departed (the worker can be delayed by a cold start).
        if depart_at <= now:
            return
        rider = sess.get(User, b.rider_id)
        if rider is None:
            return
        when = inst.depart_at.strftime("%Y-%m-%d %H:%M UTC")
        sess.add(Notification(
            user_id=rider.id,
            kind="trip.reminder",
            body=(
                f"Your ride departs at {when}. "
                "Check the trip page for any updates."
            ),
            link="/bookings",
            read=False,
            created_at=datetime.now(timezone.utc),
        ))
        sess.commit()


def _dispatch_telegram_ping(payload: dict) -> None:
    """Push a text message to a linked Telegram chat. No names, numbers
    or places beyond the departure time."""
    s = get_settings()
    token = s.telegram_bot_token
    if not token:
        return
    chat_id = str(payload.get("chat_id") or "")
    text_body = str(payload.get("text") or "")[:1000]
    if not chat_id or not text_body:
        return
    try:
        import urllib.request
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        body = json.dumps({
            "chat_id": chat_id, "text": text_body,
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
            resp.read()
    except Exception as e:  # noqa: BLE001
        logger.warning("telegram dispatch failed: %s", e)


_DISPATCH = {
    "trip_reminder": _dispatch_trip_reminder,
    "telegram_ping": _dispatch_telegram_ping,
}


def _process_due_jobs(wid: str) -> int:
    """Pick and process every due job, returning the count. Holds the
    Postgres advisory lock for the duration on Postgres; on SQLite
    the single-writer rule plus our transaction makes it safe."""
    eng = get_engine()
    key = hash(wid) & 0x7FFFFFFF
    have_lock = False
    if eng.dialect.name == "postgresql":
        have_lock = _try_advisory_lock(eng, key=key)
        if not have_lock:
            return 0
    try:
        factory = make_session_factory(eng)
        processed = 0
        # Bound the per-tick work so we don't starve the heartbeat.
        for _ in range(20):
            now = datetime.now(timezone.utc)
            with factory() as sess:
                job = claim_next(sess, now=now)
                if job is None:
                    return processed
                sess.commit()
                # Run the handler outside the claim session.
                payload = json.loads(job.payload_json or "{}")
                kind = job.kind
            handler = _DISPATCH.get(kind)
            try:
                if handler is None:
                    raise ValueError(f"unknown kind: {kind}")
                handler(payload)
                with factory() as sess:
                    row = sess.exec(select(Job).where(Job.id == job.id)).first()
                    if row is not None:
                        mark_done(sess, row)
                        sess.commit()
            except Exception as e:  # noqa: BLE001
                logger.warning("dispatch %s failed: %s", kind, e)
                with factory() as sess:
                    row = sess.exec(select(Job).where(Job.id == job.id)).first()
                    if row is not None:
                        mark_failed(sess, row, str(e))
                        sess.commit()
            processed += 1
        return processed
    finally:
        if have_lock:
            _release_advisory_lock(eng, key=key)


def _loop(wid: str, stop: dict, s) -> None:
    interval = max(5, s.heartbeat_interval_seconds)
    while not stop["v"]:
        _heartbeat(wid)
        try:
            _process_due_jobs(wid)
        except Exception as e:  # noqa: BLE001
            logger.warning("tick failed: %s", e)
        time.sleep(interval)


def run() -> None:
    """Standalone entry point: `python -m app.worker`."""
    assert_safe_secret_key()
    s = get_settings()
    wid = _worker_id()
    stop = {"v": False}

    def _stop(*_a):
        stop["v"] = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    _loop(wid, stop, s)


def run_async() -> None:
    """In-process variant; no signal handlers. Called from the FastAPI
    lifespan when RUN_WORKER_IN_PROCESS is true."""
    s = get_settings()
    wid = _worker_id()
    stop = {"v": False}
    _loop(wid, stop, s)


if __name__ == "__main__":
    run()
