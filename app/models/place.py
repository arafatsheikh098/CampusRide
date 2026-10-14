"""Places with group labels (F2). No GPS."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import Field, SQLModel


class Place(SQLModel, table=True):
    __tablename__ = "places"

    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(max_length=80, nullable=False, unique=True)
    group_label: str = Field(max_length=80, nullable=False, index=True)
    kind: str = Field(max_length=20, nullable=False)  # gate|hall|department|pickup|neighbourhood
    created_at: datetime = Field(nullable=False)
