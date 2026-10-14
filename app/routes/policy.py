"""Privacy and policy pages (F10).

GET /policy/privacy — renders the privacy notice from the i18n string
with the retention days substituted in. The page is public.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session

from ..config import get_settings
from ..db import get_session
from ..i18n import t as _t
from ..main import render

router = APIRouter(prefix="/policy", tags=["policy"])


def _lang(request: Request) -> str:
    s = get_settings()
    c = request.cookies.get("cr_lang")
    return c if c in s.supported_languages else s.default_lang


@router.get("/privacy", response_class=HTMLResponse)
def privacy(
    request: Request, session: Session = Depends(get_session),
) -> HTMLResponse:
    s = get_settings()
    lang = _lang(request)
    body = _t("policy.privacy.body", lang, default_lang=s.default_lang)
    body = body.replace("{days}", str(s.retention_days))
    return HTMLResponse(
        render(
            "policy/privacy.html",
            lang=lang, settings=s, request=request, body=body,
        )
    )
