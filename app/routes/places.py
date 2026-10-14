"""Place management (F2).

Public listing is available to approved members; the same list is the
source for the trip form. Mutations (create / edit / delete) are
moderator-only and live under /moderation/places.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from ..auth import current_user
from ..config import get_settings
from ..db import get_session
from ..main import render
from ..models.place import Place
from ..models.user import UserStatus

router = APIRouter(prefix="/places", tags=["places"])


def _lang(request: Request) -> str:
    s = get_settings()
    c = request.cookies.get("cr_lang")
    return c if c in s.supported_languages else s.default_lang


@router.get("", response_class=HTMLResponse)
def list_places(
    request: Request, session: Session = Depends(get_session)
) -> HTMLResponse:
    """Public place list. Approved members only; everyone else gets a 404
    so the page does not reveal its existence."""
    me = current_user(request, session)
    if me is None or me.status != UserStatus.APPROVED:
        raise HTTPException(status_code=404)
    lang = _lang(request)
    s = get_settings()
    places = session.exec(select(Place).order_by(Place.group_label, Place.name)).all()
    return HTMLResponse(
        render(
            "places/list.html",
            lang=lang,
            settings=s,
            request=request,
            me=me,
            places=places,
        )
    )
