"""Blocks (F8).

A block is directional: rider ↔ driver. Either side can block the other
from their own list. A block prevents matching, prevents showing each
other's trips, and prevents a booking request. The matching engine and
the booking route already consult the block list; this route is just
the user-facing CRUD.

Unblocking is allowed (idempotent). Each add/remove is audit-logged.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from ..audit import write
from ..auth import current_user, require_csrf
from ..config import get_settings
from ..db import get_session
from ..main import render
from ..models.trust import Block
from ..models.user import User, UserStatus

router = APIRouter(prefix="/blocks", tags=["blocks"])


def _lang(request: Request) -> str:
    s = get_settings()
    c = request.cookies.get("cr_lang")
    return c if c in s.supported_languages else s.default_lang


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _require_approved(me: User | None) -> User:
    if me is None or me.status != UserStatus.APPROVED:
        raise HTTPException(status_code=404)
    return me


@router.get("", response_class=HTMLResponse)
def blocks_list(
    request: Request, session: Session = Depends(get_session),
) -> HTMLResponse:
    me = _require_approved(current_user(request, session))
    lang = _lang(request)
    s = get_settings()
    rows = session.exec(
        select(Block).where(Block.blocker_id == me.id)
        .order_by(Block.created_at.desc())
    ).all()
    blocked_user_ids = [b.blocked_id for b in rows]
    users: dict[int, User] = {}
    if blocked_user_ids:
        for u in session.exec(
            select(User).where(User.id.in_(blocked_user_ids))
        ).all():
            users[u.id] = u
    return HTMLResponse(
        render(
            "blocks/list.html",
            lang=lang, settings=s, request=request, me=me,
            blocks=rows, blocked_users=users,
        )
    )


@router.post("/add")
def blocks_add(
    request: Request,
    blocked_id: int = Form(...),
    csrf_token: str | None = Form(None),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    me = _require_approved(current_user(request, session))
    require_csrf(request, csrf_token)
    if blocked_id == me.id:
        # Self-block is meaningless; ignore silently.
        return RedirectResponse("/blocks", status_code=303)
    target = session.get(User, blocked_id)
    if target is None or target.status != UserStatus.APPROVED:
        raise HTTPException(status_code=404)
    existing = session.exec(
        select(Block).where(
            Block.blocker_id == me.id,
            Block.blocked_id == blocked_id,
        )
    ).first()
    if existing is not None:
        return RedirectResponse("/blocks", status_code=303)
    block = Block(
        blocker_id=me.id, blocked_id=blocked_id,
        created_at=_now_utc(),
    )
    session.add(block)
    session.flush()
    write(
        session,
        actor_id=me.id, actor_label=me.full_name,
        action="block.add",
        target_kind="user", target_id=target.id,
        target_label=target.full_name,
    )
    session.commit()
    return RedirectResponse("/blocks", status_code=303)


@router.post("/{block_id}/remove")
def blocks_remove(
    block_id: int,
    request: Request,
    csrf_token: str | None = Form(None),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    me = _require_approved(current_user(request, session))
    require_csrf(request, csrf_token)
    block = session.get(Block, block_id)
    if block is None or block.blocker_id != me.id:
        raise HTTPException(status_code=404)
    target = session.get(User, block.blocked_id)
    session.delete(block)
    write(
        session,
        actor_id=me.id, actor_label=me.full_name,
        action="block.remove",
        target_kind="user",
        target_id=target.id if target else None,
        target_label=target.full_name if target else "",
    )
    session.commit()
    return RedirectResponse("/blocks", status_code=303)
