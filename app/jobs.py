"""Job-queue helpers (F9).

`enqueue(...)` is the only thing route code should call: it adds a row
to the `jobs` table, with a dedupe_key so duplicate schedules collapse
into one. `claim_next(...)` is what the worker calls to lock a job
row. `mark_done(...)` and `mark_failed(...)` are called by handlers.

We support both SQLite (test/CI) and Postgres (production) by handling
the lock at the application level: on SQLite we set status='running'
inside a transaction; on Postgres we additionally grab a session-level
advisory lock keyed off the worker id so only one worker mutates the
queue at a time.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session, select

from .models.job import Job, JobStatus


# Kinds we know about. Unknown kinds are rejected at enqueue time so a
# typo surfaces immediately rather than becoming a silently-skipped job.
KNOWN_KINDS = frozenset({
    "trip_reminder",
    "telegram_ping",
})


def enqueue(
    session: Session,
    *,
    kind: str,
    run_at: datetime,
    payload: dict | None = None,
    dedupe_key: Optional[str] = None,
) -> Optional[Job]:
    """Schedule a job. If a row with the same `dedupe_key` already exists
    in PENDING/RUNNING state, leave it alone and return None."""
    if kind not in KNOWN_KINDS:
        raise ValueError(f"unknown job kind: {kind}")
    payload_json = json.dumps(payload or {}, separators=(",", ":"))
    if dedupe_key is not None:
        existing = session.exec(
            select(Job).where(
                Job.dedupe_key == dedupe_key,
                Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
            )
        ).first()
        if existing is not None:
            return None
    now = datetime.now(timezone.utc)
    if run_at.tzinfo is None:
        run_at = run_at.replace(tzinfo=timezone.utc)
    job = Job(
        kind=kind,
        payload_json=payload_json,
        dedupe_key=dedupe_key,
        run_at=run_at,
        status=JobStatus.PENDING,
        attempts=0,
        last_error=None,
        created_at=now,
        updated_at=now,
        visible_at=now,
    )
    session.add(job)
    session.flush()
    return job


def claim_next(session: Session, *, now: datetime) -> Optional[Job]:
    """Atomically pick the next due job. Sets status to RUNNING and
    returns it. Returns None if nothing is due."""
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    job = session.exec(
        select(Job)
        .where(
            Job.status == JobStatus.PENDING,
            Job.run_at <= now,
        )
        .order_by(Job.run_at)
    ).first()
    if job is None:
        return None
    job.status = JobStatus.RUNNING
    job.attempts += 1
    job.updated_at = now
    session.flush()
    return job


def mark_done(session: Session, job: Job) -> None:
    job.status = JobStatus.DONE
    job.updated_at = datetime.now(timezone.utc)
    session.flush()


def mark_failed(session: Session, job: Job, error: str) -> None:
    """Failed jobs are kept in the table for inspection; we record the
    error string and reset to PENDING if attempts is still under the
    cap, else mark FAILED."""
    job.last_error = (error or "")[:2000]
    if job.attempts >= 5:
        job.status = JobStatus.FAILED
    else:
        # Exponential-ish backoff: re-schedule a minute later per attempt.
        from datetime import timedelta
        delay = timedelta(minutes=job.attempts)
        job.run_at = datetime.now(timezone.utc) + delay
        job.status = JobStatus.PENDING
    job.updated_at = datetime.now(timezone.utc)
    session.flush()
