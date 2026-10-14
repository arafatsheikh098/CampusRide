"""Recovery code single-use and storage hashing (M2 A5)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlmodel import select

from app.auth import consume_recovery_code, generate_recovery_codes
from app.db import make_session_factory
from app.models.user import RecoveryCode, User, UserStatus
from app.security import hash_token


def test_recovery_codes_work_once_and_are_hashed(engine) -> None:
    factory = make_session_factory(engine)
    with factory() as s:
        u = User(
            full_name="RC", department="CSE", batch_or_session="21",
            mobile_e164="+8801712345678",
            password_hash="x",
            status=UserStatus.APPROVED,
            is_campus_member=True, is_18_or_older=True,
            created_at=datetime.now(timezone.utc),
        )
        s.add(u)
        s.commit()
        s.refresh(u)
        codes = generate_recovery_codes(s, u)
        s.commit()
    # Storage is hashed, not the plaintext.
    with factory() as s:
        rows = s.exec(select(RecoveryCode).where(RecoveryCode.user_id == u.id)).all()
        assert len(rows) == 10
        for c in rows:
            assert c.code_hash == hash_token(c.code_hash) or len(c.code_hash) == 64
            assert c.code_hash not in codes  # plaintext never persisted
    # Use one; it should be marked used.
    with factory() as s:
        assert consume_recovery_code(s, u, codes[0]) is True
        s.commit()
        assert consume_recovery_code(s, u, codes[0]) is False  # second use fails
    with factory() as s:
        rows = s.exec(select(RecoveryCode).where(RecoveryCode.user_id == u.id)).all()
        assert sum(1 for r in rows if r.used) == 1
