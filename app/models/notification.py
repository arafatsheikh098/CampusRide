"""In-app notifications (F9)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Notification(SQLModel, table=True):
    __tablename__ = "notifications"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", nullable=False, index=True)
    kind: str = Field(max_length=40, nullable=False)
    body: str = Field(max_length=400, nullable=False)
    link: Optional[str] = Field(default=None, max_length=200, nullable=True)
    read: bool = Field(default=False, nullable=False, index=True)
    created_at: datetime = Field(nullable=False)
