"""Audit log writer. Used by every moderator action, booking accept/decline,
contact reveal, and cancellation."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Session

from .models.audit import AuditLog


def write(
    session: Session,
    *,
    actor_id: Optional[int],
    actor_label: str,
    action: str,
    target_kind: str,
    target_id: Optional[int] = None,
    target_label: str = "",
    detail: str = "",
) -> AuditLog:
    row = AuditLog(
        actor_id=actor_id,
        actor_label=actor_label,
        action=action,
        target_kind=target_kind,
        target_id=target_id,
        target_label=target_label,
        detail=detail,
        created_at=datetime.now(timezone.utc),
    )
    session.add(row)
    session.flush()
    return row
