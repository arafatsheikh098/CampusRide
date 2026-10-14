"""Driver verification (F3) — moderator-only; revocation hides from list."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.db import make_session_factory
from app.models.user import User, UserStatus
from app.security import hash_password, new_token


def _csrf(html: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', html)
    return m.group(1) if m else ""


def _make_user(engine, *, mobile, status=UserStatus.APPROVED, role="member", name="U"):
    factory = make_session_factory(engine)
    with factory() as s:
        u = User(
            full_name=name, department="CSE", batch_or_session="21",
            mobile_e164=mobile,
            password_hash=hash_password("pwpwpwpw"),
            status=status, role=role,
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


def test_anon_driver_list_is_404(client: TestClient):
    assert client.get("/driver").status_code == 404


def test_approved_user_sees_only_verified_drivers(client: TestClient, engine, settings):
    approved = _make_user(engine, mobile="+8801700000101", name="rider")
    driver = _make_user(engine, mobile="+8801700000102", name="driver",
                        status=UserStatus.APPROVED)
    # Manually mark the driver verified.
    factory = make_session_factory(engine)
    with factory() as s:
        d = s.get(User, driver)
        d.driver_verified = True
        d.driver_verified_at = datetime.now(timezone.utc)
        d.vehicle_description = "white sedan, 4 seats"
        d.vehicle_plate = "DM-1234"
        s.add(d)
        s.commit()
    # Pending user would be 404, but we don't need one for this test.
    _make_user(engine, mobile="+8801700000103", status=UserStatus.PENDING, name="pend")
    cookie = _session_cookie(approved, "member", settings)
    client.cookies.set("cr_session", cookie)
    r = client.get("/driver")
    assert r.status_code == 200
    assert "white sedan" in r.text
    # Plate must NOT appear on the public list.
    assert "DM-1234" not in r.text


def test_member_cannot_self_verify(client: TestClient, settings, engine):
    uid = _make_user(engine, mobile="+8801700000111")
    cookie = _session_cookie(uid, "member", settings)
    client.cookies.set("cr_session", cookie)
    r = client.post(
        f"/moderation/accounts/{uid}/driver-verify",
        data={"vehicle_description": "x", "vehicle_plate": "", "csrf_token": "x"},
    )
    assert r.status_code == 403


def test_mod_can_verify_and_revoke(client: TestClient, engine, settings):
    member = _make_user(engine, mobile="+8801700000121", name="verify-me")
    mod = _make_user(engine, mobile="+8801700000122", role="moderator", name="mod")
    cookie = _session_cookie(mod, "moderator", settings)
    client.cookies.set("cr_session", cookie)
    # Fetch the account detail page to get a CSRF.
    r = client.get(f"/moderation/accounts/{member}")
    assert r.status_code == 200
    csrf = _csrf(r.text)
    # Verify
    r = client.post(
        f"/moderation/accounts/{member}/driver-verify",
        data={
            "vehicle_description": "blue hatchback",
            "vehicle_plate": "DH-5678",
            "csrf_token": csrf,
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    factory = make_session_factory(engine)
    with factory() as s:
        u = s.get(User, member)
        assert u.driver_verified is True
        assert u.vehicle_description == "blue hatchback"
        assert u.vehicle_plate == "DH-5678"
    # Revoke
    r = client.get(f"/moderation/accounts/{member}")
    csrf = _csrf(r.text)
    r = client.post(
        f"/moderation/accounts/{member}/driver-revoke",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    assert r.status_code == 303
    with factory() as s:
        u = s.get(User, member)
        assert u.driver_verified is False
        assert u.vehicle_description is None
        assert u.vehicle_plate is None


def test_women_only_actions_silently_disabled_when_feature_off(
    client: TestClient, engine, settings
):
    # settings fixture has women_only_trips=False
    member = _make_user(engine, mobile="+8801700000131", name="woman")
    mod = _make_user(engine, mobile="+8801700000132", role="moderator", name="mod")
    cookie = _session_cookie(mod, "moderator", settings)
    client.cookies.set("cr_session", cookie)
    r = client.get(f"/moderation/accounts/{member}")
    csrf = _csrf(r.text)
    r = client.post(
        f"/moderation/accounts/{member}/women-only-grant",
        data={"csrf_token": csrf},
        follow_redirects=False,
    )
    # 303 redirect, no state change
    assert r.status_code == 303
    factory = make_session_factory(engine)
    with factory() as s:
        u = s.get(User, member)
        assert u.women_only_eligible is False
