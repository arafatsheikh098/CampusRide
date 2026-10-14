"""In-app notifications (F9).

GET /notifications — list of notifications for the current user,
unread first.

POST /notifications/{id}/read — mark a single notification as read.

POST /notifications/read-all — mark every notification as read.

The unread count is exposed as a JSON endpoint for the HTMX badge in
the topbar.
"""
from __future__ import annotations


from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlmodel import Session, select

from ..auth import current_user, require_csrf
from ..config import get_settings
from ..db import get_session
from ..main import render
from ..models.notification import Notification
from ..models.user import User, UserStatus

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _lang(request: Request) -> str:
    s = get_settings()
    c = request.cookies.get("cr_lang")
    return c if c in s.supported_languages else s.default_lang


def _require_approved(me: User | None) -> User:
    if me is None or me.status != UserStatus.APPROVED:
        raise HTTPException(status_code=404)
    return me


@router.get("", response_class=HTMLResponse)
def list_notifications(
    request: Request, session: Session = Depends(get_session),
) -> HTMLResponse:
    me = _require_approved(current_user(request, session))
    lang = _lang(request)
    s = get_settings()
    rows = session.exec(
        select(Notification)
        .where(Notification.user_id == me.id)
        .order_by(Notification.read.asc(), Notification.created_at.desc())
    ).all()
    unread = sum(1 for n in rows if not n.read)
    return HTMLResponse(
        render(
            "notifications/list.html",
            lang=lang, settings=s, request=request, me=me,
            notifications=rows, unread=unread,
        )
    )


@router.get("/unread", include_in_schema=False)
def unread_count(
    request: Request, session: Session = Depends(get_session),
) -> JSONResponse:
    me = current_user(request, session)
    if me is None or me.status != UserStatus.APPROVED:
        return JSONResponse({"unread": 0})
    rows = session.exec(
        select(Notification).where(
            Notification.user_id == me.id,
            Notification.read == False,  # noqa: E712
        )
    ).all()
    return JSONResponse({"unread": len(rows)})


@router.post("/{notification_id}/read")
def mark_read(
    notification_id: int,
    request: Request,
    csrf_token: str | None = Form(None),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    me = _require_approved(current_user(request, session))
    require_csrf(request, csrf_token)
    n = session.get(Notification, notification_id)
    if n is None or n.user_id != me.id:
        raise HTTPException(status_code=404)
    if not n.read:
        n.read = True
        session.commit()
    return RedirectResponse("/notifications", status_code=303)


@router.post("/read-all")
def mark_all_read(
    request: Request,
    csrf_token: str | None = Form(None),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    me = _require_approved(current_user(request, session))
    require_csrf(request, csrf_token)
    rows = session.exec(
        select(Notification).where(
            Notification.user_id == me.id,
            Notification.read == False,  # noqa: E712
        )
    ).all()
    for n in rows:
        n.read = True
    session.commit()
    return RedirectResponse("/notifications", status_code=303)
