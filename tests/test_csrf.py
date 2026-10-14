"""CSRF + route discovery (M2 A3, G8)."""
from __future__ import annotations


from fastapi.testclient import TestClient
from sqlmodel import select

from app.config import Settings
from app.db import make_session_factory
from app.models.user import User
from app.security import new_token


def _state_changing_routes(app):
    found = []
    for r in app.routes:
        m = getattr(r, "methods", None) or set()
        if not m:
            continue
        if m & {"POST", "PUT", "PATCH", "DELETE"}:
            found.append((r.path, sorted(m & {"POST", "PUT", "PATCH", "DELETE"})))
    return found


def test_every_state_changing_route_rejects_missing_csrf(client: TestClient) -> None:
    app = client.app
    pairs = _state_changing_routes(app)
    # The /me/theme and /me/lang routes are intentionally without CSRF
    excluded = {"/me/theme", "/me/lang"}
    enforced = [p for p in pairs if p[0] not in excluded]
    assert enforced, "no state-changing routes found"
    for path, _methods in enforced:
        r = client.post(path, data={})
        assert r.status_code in (400, 403, 404, 405, 422), f"{path} returned {r.status_code}"


def test_signed_in_post_without_csrf_is_rejected(client: TestClient) -> None:
    # Create a user via signup, then approve via the database to get a
    # session and try a state-changing POST without CSRF.
    r = client.get("/auth/signup")
    import re
    m = re.search(r'name="csrf_token" value="([^"]+)"', r.text)
    csrf = m.group(1)
    r = client.post(
        "/auth/signup",
        data={
            "full_name": "User", "department": "CSE", "batch_or_session": "21",
            "mobile": "01712345678", "password": "supersecret", "confirm_password": "supersecret",
            "is_campus_member": "on", "is_18_or_older": "on", "csrf_token": csrf,
        },
    )
    assert r.status_code == 200
    # Approve and grant moderator via the database.
    from app.db import get_engine
    with make_session_factory(get_engine())() as s:
        u = s.exec(select(User)).first()
        u.status = "approved"  # type: ignore[attr-defined]
        u.role = "moderator"  # type: ignore[attr-defined]
        s.add(u)
        s.commit()
        s.refresh(u)
        # Sign a session.
        from app.main import make_session_cookie
        new_csrf = new_token()
        cookie = make_session_cookie(
            Settings().secret_key, u.id, u.role.value, new_csrf,
        )
    client.cookies.set("cr_session", cookie)
    # A POST to /auth/signout without CSRF should 403.
    r = client.post("/auth/signout", data={})
    assert r.status_code == 403
