"""Telegram linking codes (F9)."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class TelegramLink(SQLModel, table=True):
    __tablename__ = "telegram_links"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", nullable=False, index=True)
    code_hash: str = Field(max_length=255, nullable=False, unique=True)
    used: bool = Field(default=False, nullable=False)
    created_at: datetime = Field(nullable=False)
    expires_at: datetime = Field(nullable=False)
