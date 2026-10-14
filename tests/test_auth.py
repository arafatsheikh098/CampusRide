"""Auth flow: signup, signin, recovery, suspension. M2 A1, A2, A5, A6."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlmodel import select
from app.db import make_session_factory

from app.models.user import RecoveryCode, User, UserStatus


def _signup(client: TestClient, **overrides) -> int:
    payload = {
        "full_name": "Test User",
        "department": "CSE",
        "batch_or_session": "21",
        "mobile": "01712345678",
        "password": "supersecret",
        "confirm_password": "supersecret",
        "is_campus_member": "on",
        "is_18_or_older": "on",
    }
    payload.update(overrides)
    # Get the pre-session cookie first.
    r = client.get("/auth/signup")
    # Pull the CSRF token from the rendered form.
    import re
    m = re.search(r'name="csrf_token" value="([^"]+)"', r.text)
    assert m, "no CSRF token rendered"
    payload["csrf_token"] = m.group(1)
    r = client.post("/auth/signup", data=payload, follow_redirects=False)
    return r.status_code


def test_signup_creates_pending_user_and_recovery_codes(client: TestClient, engine) -> None:
    code = _signup(client)
    assert code == 200
    with make_session_factory(engine)() as s:
        u = s.exec(select(User)).first()
        assert u is not None
        assert u.status == UserStatus.PENDING
        codes = s.exec(select(RecoveryCode).where(RecoveryCode.user_id == u.id)).all()
        assert len(codes) == 10
        assert all(not c.used for c in codes)
        assert all(len(c.code_hash) == 64 for c in codes)


def test_signup_validates_checkboxes(client: TestClient, engine) -> None:
    payload = {
        "full_name": "Test", "department": "CSE", "batch_or_session": "21",
        "mobile": "01712345678", "password": "supersecret", "confirm_password": "supersecret",
    }
    r = client.get("/auth/signup")
    import re
    m = re.search(r'name="csrf_token" value="([^"]+)"', r.text)
    payload["csrf_token"] = m.group(1)
    r = client.post("/auth/signup", data=payload)
    assert r.status_code == 400
    with make_session_factory(engine)() as s:
        assert s.exec(select(User)).first() is None


def test_signup_password_mismatch(client: TestClient, engine) -> None:
    code = _signup(client, confirm_password="different")
    assert code == 400
    with make_session_factory(engine)() as s:
        assert s.exec(select(User)).first() is None


def test_signin_unknown_mobile_and_wrong_password_return_same_error(
    client: TestClient, engine
) -> None:
    # Make a user, get a session, try signin with wrong creds.
    from app.security import hash_password, new_token
    from app.main import make_session_cookie
    from app.config import get_settings
    s = get_settings()
    with make_session_factory(engine)() as sess:
        u = User(
            full_name="X", department="x", batch_or_session="x",
            mobile_e164="+8801712345678",
            password_hash=hash_password("rightpass1"),
            status=UserStatus.APPROVED,
            is_campus_member=True, is_18_or_older=True,
            created_at=datetime.now(timezone.utc),
        )
        sess.add(u)
        sess.commit()
        sess.refresh(u)
        csrf = new_token()
        cookie = make_session_cookie(s.secret_key, u.id, u.role.value, csrf)
    client.cookies.set("cr_session", cookie)
    # unknown mobile
    r = client.post(
        "/auth/signin",
        data={"mobile": "01900000000", "password": "whatever1", "next": "/", "csrf_token": csrf},
    )
    assert r.status_code == 400
    # wrong password for an existing user
    r = client.post(
        "/auth/signin",
        data={"mobile": "01712345678", "password": "wrongpass1", "next": "/", "csrf_token": csrf},
    )
    assert r.status_code == 400


def test_suspended_user_session_is_rejected_immediately(client: TestClient, engine) -> None:
    from app.security import new_token
    from app.main import make_session_cookie
    from app.config import get_settings
    s = get_settings()
    with make_session_factory(engine)() as sess:
        u = User(
            full_name="Test", department="CSE", batch_or_session="21",
            mobile_e164="+8801712345678",
            password_hash="x",
            role="moderator",  # type: ignore[arg-type]
            status=UserStatus.APPROVED,
            is_campus_member=True, is_18_or_older=True,
            created_at=datetime.now(timezone.utc),
        )
        sess.add(u)
        sess.commit()
        sess.refresh(u)
        csrf = new_token()
        cookie = make_session_cookie(s.secret_key, u.id, "moderator", csrf)
        client.cookies.set("cr_session", cookie)
    r = client.get("/moderation")
    assert r.status_code == 200
    # Suspend the user
    with make_session_factory(engine)() as sess:
        u = sess.get(User, u.id)
        u.status = UserStatus.SUSPENDED
        sess.add(u)
        sess.commit()
    # Same cookie: /moderation must now hide.
    r = client.get("/moderation")
    assert r.status_code == 404


def test_pending_user_cannot_access_moderator_queue(client: TestClient, engine) -> None:
    from app.security import new_token
    from app.main import make_session_cookie
    from app.config import get_settings
    s = get_settings()
    with make_session_factory(engine)() as sess:
        u = User(
            full_name="Pending", department="CSE", batch_or_session="21",
            mobile_e164="+8801712345678",
            password_hash="x",
            role="moderator",  # type: ignore[arg-type]
            status=UserStatus.PENDING,
            is_campus_member=True, is_18_or_older=True,
            created_at=datetime.now(timezone.utc),
        )
        sess.add(u)
        sess.commit()
        sess.refresh(u)
        csrf = new_token()
        cookie = make_session_cookie(s.secret_key, u.id, "moderator", csrf)
        client.cookies.set("cr_session", cookie)
    r = client.get("/moderation")
    assert r.status_code == 404
