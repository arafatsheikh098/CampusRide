"""Audit log writer sanity (used by every later milestone; cheap to test in M1)."""
from __future__ import annotations

from sqlmodel import Session, select

from app.audit import write
from app.models.audit import AuditLog


def test_audit_writes_row(engine) -> None:
    with Session(engine) as s:
        write(
            s,
            actor_id=None,
            actor_label="system",
            action="test.event",
            target_kind="user",
            target_id=None,
            target_label="",
            detail="hello",
        )
        s.commit()
        rows = s.exec(select(AuditLog)).all()
        assert len(rows) == 1
        assert rows[0].action == "test.event"
