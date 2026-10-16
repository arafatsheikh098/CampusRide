#!/usr/bin/env python3
"""Capture README screenshots for CampusRide.

This script drives a running CampusRide instance with Playwright and
saves PNGs to docs/screenshots/. It is **not** part of the test
suite; run it by hand when the README screenshots need refreshing.

Prereqs
-------
- A running web process with the demo seed loaded.
  (``make run`` in one terminal, then ``python -m app.seed`` in
  another.)
- ``playwright install chromium`` has been run.

Usage
-----
::

    python scripts/capture_screenshots.py            # default BASE_URL=http://localhost:8000
    BASE_URL=https://ride.campus.edu python scripts/capture_screenshots.py

The script signs in as the seed moderator, signs in as a rider,
posts a trip, accepts a booking, generates a trusted contact link,
and captures each step. The trusted-contact public page is opened
in a fresh, unauthenticated context to prove the read-only flow.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

# Defer the import so the script is greppable even before Playwright
# is installed (the test suite does not require it).
try:
    from playwright.sync_api import sync_playwright  # type: ignore[import-untyped]
except ImportError:  # pragma: no cover - documented prereq
    sys.stderr.write(
        "playwright is not installed; run `pip install playwright` "
        "and `playwright install chromium` first.\n",
    )
    raise

OUT = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
OUT.mkdir(parents=True, exist_ok=True)
BASE_URL = os.environ.get("BASE_URL", "http://localhost:8000")

# Seed users from app/seed.py.
MOD_MOBILE = "01700000001"
MOD_PASSWORD = "modpass1"
RIDER_MOBILE = "01700000020"  # Daniyal Islam
RIDER_PASSWORD = "changeme"


def _shoot(page: Any, name: str) -> None:
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    print(f"  saved {path.relative_to(OUT.parent.parent)}")


def _signin(page: Any, mobile: str, password: str) -> None:
    page.goto(f"{BASE_URL}/auth/signin")
    page.fill('input[name="mobile"]', mobile)
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"]')
    page.wait_for_load_state("networkidle")


def _signout(context: Any) -> None:
    context.clear_cookies()


def main() -> int:
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(viewport={"width": 1200, "height": 800})
        page = context.new_page()

        # 1. Home (anonymous).
        print("→ home (anonymous)")
        page.goto(BASE_URL)
        page.wait_for_load_state("networkidle")
        _shoot(page, "01-home")

        # 2. Search results (signed in as a rider).
        print("→ sign in as rider, search Campus Gate → Dhanmondi 27")
        _signin(page, RIDER_MOBILE, RIDER_PASSWORD)
        page.goto(f"{BASE_URL}/search")
        page.wait_for_load_state("networkidle")
        _shoot(page, "02-search")
        _signout(context)

        # 3. Booking detail (sign in as the rider, open first trip).
        print("→ rider opens a trip and books a seat")
        _signin(page, RIDER_MOBILE, RIDER_PASSWORD)
        page.goto(f"{BASE_URL}/trips/1")
        page.wait_for_load_state("networkidle")
        # Request a seat if there's a form; capture either way.
        req = page.locator('form[action$="/bookings/new"] button[type="submit"]')
        if req.count() > 0:
            req.first.click()
            page.wait_for_load_state("networkidle")
        _shoot(page, "03-booking")
        _signout(context)

        # 4. Trusted contact public page (anonymous browser).
        print("→ generate trusted link as the rider, open it anonymously")
        # We need a fresh authenticated context to generate the link.
        gen_ctx = browser.new_context(viewport={"width": 1200, "height": 800})
        gen_page = gen_ctx.new_page()
        _signin(gen_page, RIDER_MOBILE, RIDER_PASSWORD)
        gen_page.goto(f"{BASE_URL}/bookings")
        gen_page.wait_for_load_state("networkidle")
        form = gen_page.locator('form[action*="trusted-link"]').first
        token_url: str | None = None
        if form.count() > 0:
            form.locator('button[type="submit"]').click()
            gen_page.wait_for_load_state("networkidle")
            link = gen_page.locator('a[href*="/trusted/"]').first
            if link.count() > 0:
                token_url = link.get_attribute("href")
        gen_ctx.close()
        if not token_url:
            # Fall back: pick the first /trusted/ link on the page.
            page.goto(f"{BASE_URL}/bookings")
            page.wait_for_load_state("networkidle")
            link = page.locator('a[href*="/trusted/"]').first
            if link.count() > 0:
                token_url = link.get_attribute("href")
        if not token_url:
            sys.stderr.write("could not find a trusted-contact link; skipping shot 4\n")
        else:
            anon = browser.new_context(viewport={"width": 1200, "height": 800})
            anon_page = anon.new_page()
            anon_page.goto(f"{BASE_URL}{token_url}")
            anon_page.wait_for_load_state("networkidle")
            _shoot(anon_page, "04-trusted")
            anon.close()
        _signout(context)

        # 5. Moderation queue (signed in as the moderator).
        print("→ moderation queue")
        _signin(page, MOD_MOBILE, MOD_PASSWORD)
        page.goto(f"{BASE_URL}/moderation")
        page.wait_for_load_state("networkidle")
        _shoot(page, "05-queue")
        _signout(context)

        # 6. Notifications.
        print("→ notifications")
        _signin(page, RIDER_MOBILE, RIDER_PASSWORD)
        page.goto(f"{BASE_URL}/notifications")
        page.wait_for_load_state("networkidle")
        _shoot(page, "06-notifications")

        context.close()
        browser.close()
    print("done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
