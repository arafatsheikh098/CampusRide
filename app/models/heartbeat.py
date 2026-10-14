"""Worker heartbeat (F9). The /health route reads this."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Heartbeat(SQLModel, table=True):
    __tablename__ = "heartbeats"

    id: Optional[int] = Field(default=None, primary_key=True)
    worker_id: str = Field(max_length=80, nullable=False, unique=True, index=True)
    last_seen: datetime = Field(nullable=False, index=True)
