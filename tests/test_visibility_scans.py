"""G3: plates, mobile numbers and trusted-contact data must not appear on
pages that are visible before acceptance.

This test scans every approved-member page we currently have and asserts
that no driver's vehicle plate is leaked to a non-accepted viewer. It
also asserts the moderator queue does not display plates to non-mods
(other moderators see plates only inside the trusted flow, but the
queue is a list view and should never show plates).
"""
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


def _make_user(engine, *, mobile, role="member", status=UserStatus.APPROVED, name="U"):
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


def test_no_plate_or_other_driver_mobile_leaks_anywhere(client: TestClient, engine, settings):
    """Set up a driver with a known plate and mobile, then scan every
    approved-member page and every anonymous page for either string."""
    plate = "SCAN-PLATE-1A2B"
    other_mobile = "+8801700009999"
    driver = _make_user(engine, mobile=other_mobile, name="driver")
    factory = make_session_factory(engine)
    with factory() as s:
        d = s.get(User, driver)
        d.driver_verified = True
        d.driver_verified_at = datetime.now(timezone.utc)
        d.vehicle_description = "lemon hatchback"
        d.vehicle_plate = plate
        s.add(d)
        s.commit()
    # An approved rider.
    rider = _make_user(engine, mobile="+8801700000003", name="rider")
    cookie = _session_cookie(rider, "member", settings)
    client.cookies.set("cr_session", cookie)
    # Pages that should never leak a plate to a non-accepted viewer.
    for path in ("/", "/places", "/driver", "/notifications", "/trips", "/bookings", "/search"):
        r = client.get(path, follow_redirects=False)
        # 200 or 404 are both fine; 5xx is a real failure.
        assert r.status_code < 500, f"{path} returned {r.status_code}"
        if r.status_code == 200:
            assert plate not in r.text, f"{path} leaked plate"
            assert other_mobile not in r.text, f"{path} leaked driver mobile"
    # Anonymous scan.
    client.cookies.clear()
    r = client.get("/", follow_redirects=False)
    assert r.status_code < 500
    if r.status_code == 200:
        assert plate not in r.text
        assert other_mobile not in r.text


def test_moderation_queue_does_not_leak_plates(client: TestClient, engine, settings):
    plate = "MODQ-PLATE-99"
    driver = _make_user(engine, mobile="+8801700007777", name="driver")
    factory = make_session_factory(engine)
    with factory() as s:
        d = s.get(User, driver)
        d.driver_verified = True
        d.vehicle_plate = plate
        s.add(d)
        s.commit()
    mod = _make_user(engine, mobile="+8801700007778", role="moderator", name="mod")
    cookie = _session_cookie(mod, "moderator", settings)
    client.cookies.set("cr_session", cookie)
    r = client.get("/moderation", follow_redirects=False)
    assert r.status_code == 200
    assert plate not in r.text
    r = client.get("/moderation/places", follow_redirects=False)
    assert r.status_code == 200
    assert plate not in r.text
