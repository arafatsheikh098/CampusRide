"""initial schema

Revision ID: 0001_init
Revises:
Create Date: 2026-10-14 00:00:00

Creates every table referenced in app.models.
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001_init"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("full_name", sa.String(length=120), nullable=False, index=True),
        sa.Column("department", sa.String(length=120), nullable=False),
        sa.Column("batch_or_session", sa.String(length=60), nullable=False),
        sa.Column("mobile_e164", sa.String(length=20), nullable=False, unique=True, index=True),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, index=True),
        sa.Column("driver_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("driver_verified_at", sa.DateTime(), nullable=True),
        sa.Column("vehicle_description", sa.String(length=80), nullable=True),
        sa.Column("vehicle_plate", sa.String(length=40), nullable=True),
        sa.Column("women_only_eligible", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("telegram_chat_id", sa.String(length=40), nullable=True),
        sa.Column("is_18_or_older", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("is_campus_member", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("approved_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
    )

    op.create_table(
        "recovery_codes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("code_hash", sa.String(length=255), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "login_attempts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("mobile_e164", sa.String(length=20), nullable=False, index=True),
        sa.Column("succeeded", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "places",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=80), nullable=False, unique=True),
        sa.Column("group_label", sa.String(length=80), nullable=False, index=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "trips",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("driver_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("from_place_id", sa.Integer(), sa.ForeignKey("places.id"), nullable=False),
        sa.Column("to_place_id", sa.Integer(), sa.ForeignKey("places.id"), nullable=False),
        sa.Column("earliest_departure", sa.DateTime(), nullable=False),
        sa.Column("latest_departure", sa.DateTime(), nullable=False),
        sa.Column("seats_offered", sa.Integer(), nullable=False),
        sa.Column("cost_per_seat_paisa", sa.Integer(), nullable=False),
        sa.Column("note", sa.String(length=150), nullable=True),
        sa.Column("women_only", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("recurrence_kind", sa.String(length=20), nullable=False),
        sa.Column("weekdays_mask", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("series_end_date", sa.DateTime(), nullable=True),
        sa.Column("series_start_date", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "trip_instances",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trip_id", sa.Integer(), sa.ForeignKey("trips.id"), nullable=False, index=True),
        sa.Column("depart_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("seats_taken", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=20), nullable=False, index=True),
        sa.Column("cancelled_at", sa.DateTime(), nullable=True),
        sa.Column("cancelled_by_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )

    op.create_table(
        "bookings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("trip_instance_id", sa.Integer(), sa.ForeignKey("trip_instances.id"), nullable=False, index=True),
        sa.Column("rider_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("driver_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("status", sa.String(length=24), nullable=False, index=True),
        sa.Column("rider_cancel_reason", sa.String(length=120), nullable=True),
        sa.Column("driver_cancel_reason", sa.String(length=120), nullable=True),
        sa.Column("last_minute_cancel", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "blocks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("blocker_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("blocked_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "reports",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("reporter_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("target_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True, index=True),
        sa.Column("target_trip_id", sa.Integer(), sa.ForeignKey("trips.id"), nullable=True, index=True),
        sa.Column("reason", sa.String(length=20), nullable=False),
        sa.Column("note", sa.String(length=400), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("resolved", sa.Boolean(), nullable=False, index=True),
    )

    op.create_table(
        "post_trip_checks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("booking_id", sa.Integer(), sa.ForeignKey("bookings.id"), nullable=False, index=True),
        sa.Column("responder_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("answer", sa.String(length=10), nullable=False),
        sa.Column("note", sa.String(length=400), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("body", sa.String(length=400), nullable=False),
        sa.Column("link", sa.String(length=200), nullable=True),
        sa.Column("read", sa.Boolean(), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(length=40), nullable=False, index=True),
        sa.Column("payload_json", sa.String(length=4000), nullable=False, server_default="{}"),
        sa.Column("dedupe_key", sa.String(length=120), nullable=True, index=True),
        sa.Column("run_at", sa.DateTime(), nullable=False, index=True),
        sa.Column("status", sa.String(length=20), nullable=False, index=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("last_error", sa.String(length=2000), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("visible_at", sa.DateTime(), nullable=False, index=True),
    )

    op.create_table(
        "heartbeats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("worker_id", sa.String(length=80), nullable=False, unique=True, index=True),
        sa.Column("last_seen", sa.DateTime(), nullable=False, index=True),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True, index=True),
        sa.Column("actor_label", sa.String(length=120), nullable=False),
        sa.Column("action", sa.String(length=60), nullable=False, index=True),
        sa.Column("target_kind", sa.String(length=20), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=True, index=True),
        sa.Column("target_label", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("detail", sa.String(length=2000), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False, index=True),
    )

    op.create_table(
        "telegram_links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("code_hash", sa.String(length=255), nullable=False, unique=True),
        sa.Column("used", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    for tbl in (
        "telegram_links",
        "audit_log",
        "heartbeats",
        "jobs",
        "notifications",
        "post_trip_checks",
        "reports",
        "blocks",
        "bookings",
        "trip_instances",
        "trips",
        "places",
        "login_attempts",
        "recovery_codes",
        "users",
    ):
        op.drop_table(tbl)