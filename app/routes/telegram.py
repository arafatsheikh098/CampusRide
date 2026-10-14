"""Telegram linking and webhook (F9).

Flow:
  1. Member visits `/me/telegram` (or POSTs the same) to receive a
     short one-time code, hashed and stored in `telegram_links`.
  2. They send the code to the Telegram bot.
  3. The bot POSTs to `/telegram/webhook` with the secret token in the
     `X-Telegram-Bot-Api-Secret-Token` header.
  4. We mark the link as used and store the chat id on the user.

The webhook is secret-token-authenticated and only fires when
`telegram_bot_token` and `telegram_webhook_secret` are configured.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Form, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from ..audit import write
from ..auth import current_user, require_csrf
from ..config import get_settings
from ..db import get_session
from ..main import render
from ..models.telegram_link import TelegramLink
from ..models.user import User, UserStatus
from ..security import constant_time_eq, hash_token, new_token

router = APIRouter(prefix="/telegram", tags=["telegram"])

_LINK_TTL_MINUTES = 15


def _lang(request: Request) -> str:
    s = get_settings()
    c = request.cookies.get("cr_lang")
    return c if c in s.supported_languages else s.default_lang


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _telegram_enabled() -> bool:
    s = get_settings()
    return bool(s.telegram_bot_token) and bool(s.telegram_webhook_secret)


@router.get("/link", response_class=HTMLResponse)
def link_page(
    request: Request, session: Session = Depends(get_session),
) -> HTMLResponse:
    me = current_user(request, session)
    if me is None or me.status != UserStatus.APPROVED:
        raise HTTPException(status_code=404)
    lang = _lang(request)
    s = get_settings()
    return HTMLResponse(
        render(
            "telegram/link.html",
            lang=lang, settings=s, request=request, me=me,
            enabled=_telegram_enabled(),
            chat_id=me.telegram_chat_id,
            sent_code=request.query_params.get("code", ""),
        )
    )


@router.post("/link")
def link_create(
    request: Request,
    csrf_token: str | None = Form(None),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    me = current_user(request, session)
    if me is None or me.status != UserStatus.APPROVED:
        raise HTTPException(status_code=404)
    require_csrf(request, csrf_token)
    if not _telegram_enabled():
        # Feature is disabled: redirect with no code.
        return RedirectResponse("/telegram/link", status_code=303)
    raw = new_token()
    code_hash = hash_token(raw)
    expires_at = _now_utc() + timedelta(minutes=_LINK_TTL_MINUTES)
    link = TelegramLink(
        user_id=me.id,
        code_hash=code_hash,
        used=False,
        created_at=_now_utc(),
        expires_at=expires_at,
    )
    session.add(link)
    session.flush()
    write(
        session,
        actor_id=me.id, actor_label=me.full_name,
        action="telegram.link.create",
        target_kind="telegram_link", target_id=link.id,
        target_label=f"#{link.id}",
    )
    session.commit()
    return RedirectResponse(
        url=f"/telegram/link?code={raw}", status_code=303,
    )


@router.post("/webhook")
async def webhook(
    request: Request,
    session: Session = Depends(get_session),
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
) -> dict:
    """Called by Telegram when a user sends the bot the link code. We
    only need `chat.id` + the text. The secret token in the header
    authenticates the caller."""
    s = get_settings()
    if not _telegram_enabled():
        raise HTTPException(status_code=404)
    if x_telegram_bot_api_secret_token is None or not constant_time_eq(
        x_telegram_bot_api_secret_token, s.telegram_webhook_secret or "",
    ):
        raise HTTPException(status_code=403)
    import json as _json
    try:
        body = await request.body()
        payload = _json.loads(body or b"{}")
    except Exception:
        raise HTTPException(status_code=400) from None
    msg = payload.get("message") or payload.get("edited_message") or {}
    chat = msg.get("chat") or {}
    chat_id = str(chat.get("id") or "")
    text = str(msg.get("text") or "").strip()
    if not chat_id or not text:
        return {"ok": True}
    # Find the link by hashing the text.
    code_hash = hash_token(text)
    link = session.exec(
        select(TelegramLink).where(
            TelegramLink.code_hash == code_hash,
            TelegramLink.used == False,  # noqa: E712
        )
    ).first()
    if link is None:
        return {"ok": False}
    if link.expires_at.tzinfo is None:
        link.expires_at = link.expires_at.replace(tzinfo=timezone.utc)
    if link.expires_at < _now_utc():
        return {"ok": False}
    user = session.get(User, link.user_id)
    if user is not None:
        user.telegram_chat_id = chat_id
        link.used = True
        write(
            session,
            actor_id=user.id, actor_label=user.full_name,
            action="telegram.link.used",
            target_kind="user", target_id=user.id,
            target_label=user.full_name,
        )
        session.commit()
    return {"ok": True}


@router.post("/unlink")
def unlink(
    request: Request,
    csrf_token: str | None = Form(None),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    me = current_user(request, session)
    if me is None or me.status != UserStatus.APPROVED:
        raise HTTPException(status_code=404)
    require_csrf(request, csrf_token)
    if me.telegram_chat_id:
        me.telegram_chat_id = None
        write(
            session,
            actor_id=me.id, actor_label=me.full_name,
            action="telegram.unlink",
            target_kind="user", target_id=me.id,
            target_label=me.full_name,
        )
        session.commit()
    return RedirectResponse("/telegram/link", status_code=303)
