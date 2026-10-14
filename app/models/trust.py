"""Blocks, reports and post-trip checks (F8)."""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class ReportReason(str, enum.Enum):
    SAFETY = "safety"
    NO_SHOW = "no_show"
    HARASSMENT = "harassment"
    OTHER = "other"


class PostTripAnswer(str, enum.Enum):
    OK = "ok"
    PROBLEM = "problem"


class Block(SQLModel, table=True):
    __tablename__ = "blocks"

    id: Optional[int] = Field(default=None, primary_key=True)
    blocker_id: int = Field(foreign_key="users.id", nullable=False, index=True)
    blocked_id: int = Field(foreign_key="users.id", nullable=False, index=True)
    created_at: datetime = Field(nullable=False)


class Report(SQLModel, table=True):
    __tablename__ = "reports"

    id: Optional[int] = Field(default=None, primary_key=True)
    reporter_id: int = Field(foreign_key="users.id", nullable=False, index=True)
    target_user_id: Optional[int] = Field(
        default=None, foreign_key="users.id", nullable=True, index=True
    )
    target_trip_id: Optional[int] = Field(
        default=None, foreign_key="trips.id", nullable=True, index=True
    )
    reason: ReportReason = Field(default=ReportReason.OTHER, nullable=False)
    note: Optional[str] = Field(default=None, max_length=400, nullable=True)
    created_at: datetime = Field(nullable=False)
    resolved: bool = Field(default=False, nullable=False, index=True)


class PostTripCheck(SQLModel, table=True):
    __tablename__ = "post_trip_checks"

    id: Optional[int] = Field(default=None, primary_key=True)
    booking_id: int = Field(foreign_key="bookings.id", nullable=False, index=True)
    responder_id: int = Field(foreign_key="users.id", nullable=False, index=True)
    answer: PostTripAnswer = Field(nullable=False)
    note: Optional[str] = Field(default=None, max_length=400, nullable=True)
    created_at: datetime = Field(nullable=False)


class TrustedContactLink(SQLModel, table=True):
    """Read-only trusted-contact link (F7). The token is random (>=128 bits)
    and only the SHA-256 hash is stored; the route compares the hash of
    the presented token. `expires_at` defaults to trip end + 2 hours."""
    __tablename__ = "trusted_contact_links"

    id: Optional[int] = Field(default=None, primary_key=True)
    booking_id: int = Field(foreign_key="bookings.id", nullable=False, index=True)
    trip_instance_id: int = Field(
        foreign_key="trip_instances.id", nullable=False, index=True,
    )
    created_by_id: int = Field(foreign_key="users.id", nullable=False, index=True)
    token_hash: str = Field(max_length=64, nullable=False, unique=True, index=True)
    created_at: datetime = Field(nullable=False)
    expires_at: datetime = Field(nullable=False, index=True)
