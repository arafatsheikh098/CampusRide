"""Append-only audit log for moderator and safety actions."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"

    id: Optional[int] = Field(default=None, primary_key=True)
    actor_id: Optional[int] = Field(default=None, foreign_key="users.id", nullable=True, index=True)
    # If the actor (the user) was deleted, the audit row remains; actor name
    # is captured at write time so it stays readable.
    actor_label: str = Field(max_length=120, nullable=False)
    action: str = Field(max_length=60, nullable=False, index=True)
    target_kind: str = Field(max_length=20, nullable=False)
    target_id: Optional[int] = Field(default=None, nullable=True, index=True)
    target_label: str = Field(max_length=200, nullable=False, default="")
    detail: str = Field(max_length=2000, nullable=False, default="")
    created_at: datetime = Field(nullable=False, index=True)
