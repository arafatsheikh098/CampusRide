"""Driver verification pages (F3).

The moderator actions live in `app/routes/moderation.py`. This module
exposes a small member-facing list of driver-verified members (vehicle
description only, no plates) and the per-member "become a driver" /
"my driver status" landing.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from ..auth import current_user
from ..config import get_settings
from ..db import get_session
from ..main import render
from ..models.user import User, UserStatus

router = APIRouter(prefix="/driver", tags=["driver"])


def _lang(request: Request) -> str:
    s = get_settings()
    c = request.cookies.get("cr_lang")
    return c if c in s.supported_languages else s.default_lang


@router.get("", response_class=HTMLResponse)
def driver_landing(
    request: Request, session: Session = Depends(get_session)
) -> HTMLResponse:
    me = current_user(request, session)
    if me is None or me.status != UserStatus.APPROVED:
        raise HTTPException(status_code=404)
    lang = _lang(request)
    s = get_settings()
    drivers = session.exec(
        select(User).where(
            User.driver_verified == True,  # noqa: E712
            User.status == UserStatus.APPROVED,
        ).order_by(User.full_name)
    ).all()
    return HTMLResponse(
        render(
            "driver/list.html",
            lang=lang, settings=s, request=request, me=me, drivers=drivers,
        )
    )
