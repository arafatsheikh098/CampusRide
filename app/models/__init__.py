"""SQLModel entity definitions for CampusRide.

This package exists so `app.db.init_db()` and Alembic can find every model.
The actual definitions live in submodules grouped by feature.
"""
from .user import (
    User,
    UserStatus,
    UserRole,
    RecoveryCode,
    LoginAttempt,
)
from .place import Place
from .trip import (
    Trip,
    TripInstance,
    TripStatus,
    RecurrenceKind,
)
from .booking import (
    Booking,
    BookingStatus,
)
from .trust import (
    Block,
    Report,
    PostTripCheck,
    ReportReason,
    PostTripAnswer,
)
from .notification import Notification
from .job import Job, JobStatus
from .heartbeat import Heartbeat
from .audit import AuditLog
from .telegram_link import TelegramLink

__all__ = [
    "User",
    "UserStatus",
    "UserRole",
    "RecoveryCode",
    "LoginAttempt",
    "Place",
    "Trip",
    "TripInstance",
    "TripStatus",
    "RecurrenceKind",
    "Booking",
    "BookingStatus",
    "Block",
    "Report",
    "PostTripCheck",
    "ReportReason",
    "PostTripAnswer",
    "Notification",
    "Job",
    "JobStatus",
    "Heartbeat",
    "AuditLog",
    "TelegramLink",
]
