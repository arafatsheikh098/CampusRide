"""Database-backed job queue (F9)."""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class Job(SQLModel, table=True):
    __tablename__ = "jobs"

    id: Optional[int] = Field(default=None, primary_key=True)
    kind: str = Field(max_length=40, nullable=False, index=True)
    payload_json: str = Field(max_length=4000, nullable=False, default="{}")
    dedupe_key: Optional[str] = Field(default=None, max_length=120, nullable=True, index=True)
    run_at: datetime = Field(nullable=False, index=True)
    status: JobStatus = Field(default=JobStatus.PENDING, nullable=False, index=True)
    attempts: int = Field(default=0, nullable=False)
    last_error: Optional[str] = Field(default=None, max_length=2000, nullable=True)
    created_at: datetime = Field(nullable=False)
    updated_at: datetime = Field(nullable=False)
    visible_at: datetime = Field(nullable=False, index=True)
