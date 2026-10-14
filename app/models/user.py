"""User, roles, recovery codes and login attempts."""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class UserStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUSPENDED = "suspended"


class UserRole(str, enum.Enum):
    MEMBER = "member"
    MODERATOR = "moderator"


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: Optional[int] = Field(default=None, primary_key=True)
    full_name: str = Field(max_length=120, nullable=False, index=True)
    department: str = Field(max_length=120, nullable=False)
    batch_or_session: str = Field(max_length=60, nullable=False)
    mobile_e164: str = Field(max_length=20, nullable=False, unique=True, index=True)
    password_hash: str = Field(max_length=255, nullable=False)

    role: UserRole = Field(default=UserRole.MEMBER, nullable=False)
    status: UserStatus = Field(default=UserStatus.PENDING, nullable=False, index=True)

    # Driver verification (F3). The flag is set by a moderator; the app stores
    # only the flag, the date and a short vehicle description — never a
    # license number or document.
    driver_verified: bool = Field(default=False, nullable=False)
    driver_verified_at: Optional[datetime] = Field(default=None, nullable=True)
    vehicle_description: Optional[str] = Field(default=None, max_length=80, nullable=True)
    vehicle_plate: Optional[str] = Field(default=None, max_length=40, nullable=True)

    # Women-only eligibility (F5). Stored only as a boolean.
    women_only_eligible: bool = Field(default=False, nullable=False)

    # Telegram link (F9, optional).
    telegram_chat_id: Optional[str] = Field(default=None, nullable=True)

    is_18_or_older: bool = Field(default=False, nullable=False)
    is_campus_member: bool = Field(default=False, nullable=False)

    created_at: datetime = Field(nullable=False)
    approved_at: Optional[datetime] = Field(default=None, nullable=True)
    approved_by_id: Optional[int] = Field(default=None, foreign_key="users.id", nullable=True)


class RecoveryCode(SQLModel, table=True):
    __tablename__ = "recovery_codes"

    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="users.id", nullable=False, index=True)
    code_hash: str = Field(max_length=255, nullable=False)
    used: bool = Field(default=False, nullable=False)
    created_at: datetime = Field(nullable=False)
    used_at: Optional[datetime] = Field(default=None, nullable=True)


class LoginAttempt(SQLModel, table=True):
    __tablename__ = "login_attempts"

    id: Optional[int] = Field(default=None, primary_key=True)
    mobile_e164: str = Field(max_length=20, nullable=False, index=True)
    succeeded: bool = Field(default=False, nullable=False)
    created_at: datetime = Field(nullable=False)
