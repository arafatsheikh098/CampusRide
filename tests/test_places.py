"""Place CRUD (F2) — moderator-only mutations; public list visible only to
approved members; pending/rejected/suspended users get a 404.
"""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.db import make_session_factory
from app.models.place import Place
from app.models.user import User, UserStatus
from app.security import hash_password, new_token
from datetime import datetime, timezone


def _csrf(html: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return m.group(1) if m else ""


@pytest.fixture()
def approved_user(engine):
    factory = make_session_factory(engine)
    with factory() as s:
        u = User(
            full_name="A", department="CSE", batch_or_session="21",
            mobile_e164="+8801700000001",
            password_hash=hash_password("pwpwpwpw"),
            status=UserStatus.APPROVED, role="member",
            is_campus_member=True, is_18_or_older=True,
            created_at=datetime.now(timezone.utc),
        )
        s.add(u)
        s.commit()
        s.refresh(u)
        return u.id


@pytest.fixture()
def mod_user(engine):
    factory = make_session_factory(engine)
    with factory() as s:
        u = User(
            full_name="M", department="CSE", batch_or_session="21",
            mobile_e164="+8801700000002",
            password_hash=hash_password("pwpwpwpw"),
            status=UserStatus.APPROVED, role="moderator",
            is_campus_member=True, is_18_or_older=True,
            created_at=datetime.now(timezone.utc),
        )
        s.add(u)
        s.commit()
        s.refresh(u)
        return u.id


def _session_cookie(uid: int, role: str, settings) -> str:
    from app.main import make_session_cookie
    return make_session_cookie(settings.secret_key, uid, role, new_token())


def test_anon_places_list_is_404(client: TestClient):
    assert client.get("/places").status_code == 404


def test_pending_user_places_list_is_404(client: TestClient, engine, settings):
    factory = make_session_factory(engine)
    with factory() as s:
        u = User(
            full_name="P", department="CSE", batch_or_session="21",
            mobile_e164="+8801700000011",
            password_hash=hash_password("pwpwpwpw"),
            status=UserStatus.PENDING, role="member",
            is_campus_member=True, is_18_or_older=True,
            created_at=datetime.now(timezone.utc),
        )
        s.add(u)
        s.commit()
        s.refresh(u)
        cookie = _session_cookie(u.id, u.role.value, settings)
    client.cookies.set("cr_session", cookie)
    assert client.get("/places").status_code == 404


def test_approved_user_sees_places(client: TestClient, engine, settings, approved_user):
    factory = make_session_factory(engine)
    with factory() as s:
        s.add(Place(name="Gate A", group_label="Main", kind="gate",
                    created_at=datetime.now(timezone.utc)))
        s.commit()
    cookie = _session_cookie(approved_user, "member", settings)
    client.cookies.set("cr_session", cookie)
    r = client.get("/places")
    assert r.status_code == 200
    assert "Gate A" in r.text


def test_member_cannot_create_place(client: TestClient, settings, approved_user):
    cookie = _session_cookie(approved_user, "member", settings)
    client.cookies.set("cr_session", cookie)
    # No form CSRF needed for a 404/403 short-circuit.
    r = client.post(
        "/moderation/places",
        data={"name": "X", "group_label": "Y", "kind": "gate", "csrf_token": "x"},
    )
    assert r.status_code == 404


def test_mod_can_create_and_delete_place(client: TestClient, engine, settings, mod_user):
    cookie = _session_cookie(mod_user, "moderator", settings)
    client.cookies.set("cr_session", cookie)
    # GET first to capture CSRF.
    r = client.get("/moderation/places")
    csrf = _csrf(r.text)
    r = client.post(
        "/moderation/places",
        data={"name": "Library", "group_label": "Central", "kind": "hall", "csrf_token": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 303
    factory = make_session_factory(engine)
    with factory() as s:
        rows = s.exec(__import__("sqlmodel").select(Place)).all()
        assert any(p.name == "Library" for p in rows)
    # Now delete
    r = client.get("/moderation/places")
    csrf = _csrf(r.text)
    # Find id
    with factory() as s:
        p = next(p for p in s.exec(__import__("sqlmodel").select(Place)).all() if p.name == "Library")
        pid = p.id
    r = client.post(
        f"/moderation/places/{pid}/delete",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 303
    with factory() as s:
        rows = s.exec(__import__("sqlmodel").select(Place)).all()
        assert all(p.name != "Library" for p in rows)


def test_place_create_validates_kind(client: TestClient, settings, mod_user):
    cookie = _session_cookie(mod_user, "moderator", settings)
    client.cookies.set("cr_session", cookie)
    r = client.get("/moderation/places")
    csrf = _csrf(r.text)
    r = client.post(
        "/moderation/places",
        data={"name": "Bad", "group_label": "G", "kind": "spaceship", "csrf_token": csrf},
    )
    assert r.status_code == 400
    assert "Unknown kind" in r.text
