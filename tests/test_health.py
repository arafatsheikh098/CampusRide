"""/health returns ok=true when the database is reachable."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.models.heartbeat import Heartbeat


def test_health_degrades_without_heartbeat(client: TestClient, engine) -> None:
    r = client.get("/health")
    assert r.status_code == 503  # no heartbeat yet
    body = r.json()
    assert body["db"] is True
    assert body["worker"]["heartbeat_age_seconds"] is None
    assert body["ok"] is False


def test_health_ok_with_fresh_heartbeat(client: TestClient, engine) -> None:
    with Session(engine) as s:
        s.add(Heartbeat(worker_id="test-worker", last_seen=datetime.now(timezone.utc)))
        s.commit()
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["db"] is True
    assert body["worker"]["healthy"] is True
    assert body["ok"] is True


def test_home_renders_in_english(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "CampusRide" in r.text
    # CSP header is present.
    assert "Content-Security-Policy" in r.headers
    assert "frame-ancestors" in r.headers["Content-Security-Policy"]


def test_home_renders_in_bangla(client: TestClient) -> None:
    r = client.get("/", cookies={"cr_lang": "bn"})
    assert r.status_code == 200
    assert "ক্যাম্পাসরাইড" in r.text


def test_404_custom_page(client: TestClient) -> None:
    r = client.get("/does-not-exist")
    assert r.status_code == 404
    assert "404" in r.text


def test_theme_toggle_sets_cookie_and_returns_next(client: TestClient) -> None:
    r = client.post("/me/theme", data={"next": "/search"})
    assert r.status_code == 204
    assert r.cookies.get("cr_theme") in ("light", "dark")
    assert r.headers.get("X-Cr-Next") == "/search"


def test_lang_toggle_cycles(client: TestClient) -> None:
    r = client.post("/me/lang", data={"next": "/"})
    assert r.status_code == 204
    assert r.cookies.get("cr_lang") == "bn"
    r2 = client.post("/me/lang", data={"next": "/"}, cookies={"cr_lang": "bn"})
    assert r2.cookies.get("cr_lang") == "en"
