"""User profile. M1 only ships the theme/language toggles."""
from __future__ import annotations

from fastapi import APIRouter, Form, Request, Response

from ..config import get_settings
from ..main import COOKIE_NAME, make_session_cookie  # noqa: F401  (re-exported)

router = APIRouter(prefix="/me", tags=["profile"])


@router.post("/theme", include_in_schema=False)
async def toggle_theme(request: Request, next: str = Form("/")) -> Response:
    """Flip the `cr_theme` cookie between 'light' and 'dark'."""
    s = get_settings()
    current = request.cookies.get("cr_theme")
    new = "dark" if current != "dark" else "light"
    resp = Response(status_code=204)
    resp.set_cookie(
        "cr_theme",
        new,
        max_age=60 * 60 * 24 * 365,
        httponly=False,  # readable by the small JS so the page re-themes immediately
        samesite="lax",
        secure=s.is_production,
        path="/",
    )
    resp.headers["X-Cr-Next"] = next or "/"
    return resp


@router.post("/lang", include_in_schema=False)
async def toggle_lang(request: Request, next: str = Form("/")) -> Response:
    s = get_settings()
    current = request.cookies.get("cr_lang") or s.default_lang
    langs = s.supported_languages
    if current in langs and len(langs) > 1:
        idx = (langs.index(current) + 1) % len(langs)
        new = langs[idx]
    else:
        new = s.default_lang
    resp = Response(status_code=204)
    resp.set_cookie(
        "cr_lang",
        new,
        max_age=60 * 60 * 24 * 365,
        httponly=False,
        samesite="lax",
        secure=s.is_production,
        path="/",
    )
    resp.headers["X-Cr-Next"] = next or "/"
    return resp
