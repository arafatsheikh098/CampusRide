"""Login rate limit (M2 A4)."""
from __future__ import annotations

import datetime as dt

from freezegun import freeze_time

from app.auth import LOGIN_MAX_FAILS, recent_failures, record_login_attempt
from app.db import make_session_factory
from app.models.user import User, UserStatus
from app.security import hash_password


def test_rate_limit_triggers_on_sixth_attempt_in_window(engine):
    factory = make_session_factory(engine)
    with factory() as s:
        u = User(
            full_name="RL", department="CSE", batch_or_session="21",
            mobile_e164="+8801712345678",
            password_hash=hash_password("rightpass1"),
            status=UserStatus.APPROVED,
            is_campus_member=True, is_18_or_older=True,
            created_at=dt.datetime.now(dt.timezone.utc),
        )
        s.add(u)
        s.commit()

    base = dt.datetime.now(dt.timezone.utc)
    with freeze_time(base) as ft:
        with factory() as s:
            for _ in range(5):
                record_login_attempt(s, "+8801712345678", False)
            s.commit()
            assert recent_failures(s, "+8801712345678") == 5
        with factory() as s:
            record_login_attempt(s, "+8801712345678", False)
            s.commit()
            assert recent_failures(s, "+8801712345678") == 6
            assert recent_failures(s, "+8801712345678") > LOGIN_MAX_FAILS
        # Move past the 15-minute window
        ft.tick(delta=dt.timedelta(minutes=16))
        with factory() as s:
            assert recent_failures(s, "+8801712345678") == 0
