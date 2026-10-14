"""Trips and dated instances (F4)."""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class RecurrenceKind(str, enum.Enum):
    ONE_OFF = "one_off"
    WEEKLY = "weekly"


class TripStatus(str, enum.Enum):
    ACTIVE = "active"
    CANCELLED = "cancelled"
    REMOVED = "removed"


class Trip(SQLModel, table=True):
    __tablename__ = "trips"

    id: Optional[int] = Field(default=None, primary_key=True)
    driver_id: int = Field(foreign_key="users.id", nullable=False, index=True)
    from_place_id: int = Field(foreign_key="places.id", nullable=False)
    to_place_id: int = Field(foreign_key="places.id", nullable=False)
    earliest_departure: datetime = Field(nullable=False)
    latest_departure: datetime = Field(nullable=False)
    seats_offered: int = Field(ge=1, le=6, nullable=False)
    cost_per_seat_paisa: int = Field(ge=0, nullable=False)
    note: Optional[str] = Field(default=None, max_length=150, nullable=True)
    women_only: bool = Field(default=False, nullable=False)

    recurrence_kind: RecurrenceKind = Field(default=RecurrenceKind.ONE_OFF, nullable=False)
    weekdays_mask: int = Field(default=0, nullable=False)  # bit i set = weekday i
    series_end_date: Optional[datetime] = Field(default=None, nullable=True)
    series_start_date: datetime = Field(nullable=False)

    created_at: datetime = Field(nullable=False)
    updated_at: datetime = Field(nullable=False)


class TripInstance(SQLModel, table=True):
    __tablename__ = "trip_instances"

    id: Optional[int] = Field(default=None, primary_key=True)
    trip_id: int = Field(foreign_key="trips.id", nullable=False, index=True)
    depart_at: datetime = Field(nullable=False, index=True)
    seats_taken: int = Field(default=0, ge=0, nullable=False)
    status: TripStatus = Field(default=TripStatus.ACTIVE, nullable=False, index=True)
    cancelled_at: Optional[datetime] = Field(default=None, nullable=True)
    cancelled_by_id: Optional[int] = Field(default=None, foreign_key="users.id", nullable=True)
    # If seats were booked, do not auto-cancel on series edit; freeze this row.
    locked: bool = Field(default=False, nullable=False)
