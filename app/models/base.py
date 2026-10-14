"""Shared SQLModel base with common columns."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import Field, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin(SQLModel):
    created_at: datetime = Field(default_factory=_now, nullable=False)
