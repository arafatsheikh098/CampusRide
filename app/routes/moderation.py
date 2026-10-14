"""Moderator routes: account approval, suspension, audit review."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from ..audit import write
from ..auth import current_user, require_csrf, require_moderator
from ..config import get_settings
from ..db import get_session
from ..main import render
from ..models.user import User, UserStatus

router = APIRouter(prefix="/moderation", tags=["moderation"])


def _lang(request: Request) -> str:
    s = get_settings()
    c = request.cookies.get("cr_lang")
    return c if c in s.supported_languages else s.default_lang


@router.get("", response_class=HTMLResponse)
def queue(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    lang = _lang(request)
    s = get_settings()
    me = current_user(request, session)
    if (
        me is None
        or me.role.value != "moderator"
        or me.status != UserStatus.APPROVED
    ):
        # Hide the queue from anyone who is not an approved moderator:
        # 404 rather than 403 to avoid revealing the URL.
        raise HTTPException(status_code=404)
    pending = session.exec(
        select(User).where(User.status == UserStatus.PENDING).order_by(User.created_at)
    ).all()
    # Pull the CSRF token from the session cookie so the forms can render it.
    from ..main import read_session_cookie
    data = read_session_cookie(s.secret_key, request.cookies.get("cr_session", ""))
    csrf = str((data or {}).get("csrf", ""))
    return HTMLResponse(
        render(
            "moderation/queue.html",
            lang=lang,
            settings=s,
            request=request,
            pending=pending,
            me=me,
            csrf=csrf,
        )
    )


@router.post("/accounts/{user_id}/approve")
def approve(
    user_id: int,
    request: Request,
    csrf_token: str | None = Form(None),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    me = current_user(request, session)
    require_moderator(me)
    require_csrf(request, csrf_token)
    target = session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404)
    if target.status == UserStatus.APPROVED:
        return RedirectResponse("/moderation", status_code=303)
    # Enforce member cap.
    s = get_settings()
    approved = session.exec(
        select(User).where(User.status == UserStatus.APPROVED)
    ).all()
    if len(approved) >= s.member_cap:
        raise HTTPException(status_code=409, detail="member_cap_reached")
    target.status = UserStatus.APPROVED
    target.approved_at = datetime.now(timezone.utc)
    target.approved_by_id = me.id
    write(
        session,
        actor_id=me.id,
        actor_label=me.full_name,
        action="user.approve",
        target_kind="user",
        target_id=target.id,
        target_label=target.full_name,
    )
    session.commit()
    return RedirectResponse("/moderation", status_code=303)


@router.post("/accounts/{user_id}/reject")
def reject(
    user_id: int,
    request: Request,
    csrf_token: str | None = Form(None),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    me = current_user(request, session)
    require_moderator(me)
    require_csrf(request, csrf_token)
    target = session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404)
    if target.status == UserStatus.REJECTED:
        return RedirectResponse("/moderation", status_code=303)
    target.status = UserStatus.REJECTED
    write(
        session,
        actor_id=me.id,
        actor_label=me.full_name,
        action="user.reject",
        target_kind="user",
        target_id=target.id,
        target_label=target.full_name,
    )
    session.commit()
    return RedirectResponse("/moderation", status_code=303)


@router.post("/accounts/{user_id}/suspend")
def suspend(
    user_id: int,
    request: Request,
    csrf_token: str | None = Form(None),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    me = current_user(request, session)
    require_moderator(me)
    require_csrf(request, csrf_token)
    target = session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404)
    target.status = UserStatus.SUSPENDED
    write(
        session,
        actor_id=me.id,
        actor_label=me.full_name,
        action="user.suspend",
        target_kind="user",
        target_id=target.id,
        target_label=target.full_name,
    )
    session.commit()
    return RedirectResponse("/moderation", status_code=303)
