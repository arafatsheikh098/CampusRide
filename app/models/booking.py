"""Seat bookings (F6)."""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class BookingStatus(str, enum.Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    DECLINED = "declined"
    CANCELLED_BY_RIDER = "cancelled_by_rider"
    CANCELLED_BY_DRIVER = "cancelled_by_driver"


class Booking(SQLModel, table=True):
    __tablename__ = "bookings"

    id: Optional[int] = Field(default=None, primary_key=True)
    trip_instance_id: int = Field(
        foreign_key="trip_instances.id", nullable=False, index=True
    )
    rider_id: int = Field(foreign_key="users.id", nullable=False, index=True)
    driver_id: int = Field(foreign_key="users.id", nullable=False, index=True)
    status: BookingStatus = Field(default=BookingStatus.PENDING, nullable=False, index=True)
    rider_cancel_reason: Optional[str] = Field(default=None, max_length=120, nullable=True)
    driver_cancel_reason: Optional[str] = Field(default=None, max_length=120, nullable=True)
    last_minute_cancel: bool = Field(default=False, nullable=False)
    created_at: datetime = Field(nullable=False)
    decided_at: Optional[datetime] = Field(default=None, nullable=True)
