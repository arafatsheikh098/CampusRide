"""User profile. M1 ships theme/lang toggles; M9 adds delete-my-data (F10)."""
from __future__ import annotations

import secrets
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from ..audit import write as audit_write
from ..auth import clear_session, current_user, require_csrf
from ..booking import held_a_seat
from ..config import get_settings
from ..db import get_session
from ..main import render
from ..models.booking import Booking, BookingStatus
from ..models.trip import Trip, TripInstance, TripStatus
from ..models.user import User, UserStatus
from ..security import hash_password

router = APIRouter(prefix="/me", tags=["profile"])


def _lang(request: Request) -> str:
    s = get_settings()
    c = request.cookies.get("cr_lang")
    return c if c in s.supported_languages else s.default_lang


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


# --- Delete my data (F10) ------------------------------------------------


def _anonymize_user(s: Session, u: User) -> None:
    """Scrub PII on the user row. The id, role, and audit history stay."""
    placeholder = f"deleted-user-{u.id}"
    u.full_name = placeholder[:120]
    u.department = "N/A"
    u.batch_or_session = "N/A"
    # Replace the mobile with a unique placeholder so the unique index
    # stays valid; the original is no longer recoverable from this column.
    # The id is appended so two deleted users never collide.
    u.mobile_e164 = f"+0000000000{u.id}"[-20:]
    # Lock out further sign-ins: the password hash is replaced with a
    # random value; the original is dropped. We use a 32-byte random
    # argon2 hash so the column remains a hash, not a plaintext marker.
    u.password_hash = hash_password(secrets.token_urlsafe(32))
    # Stop driver-specific attributes: trip listings, vehicle text, plate.
    u.driver_verified = False
    u.driver_verified_at = None
    u.vehicle_description = None
    u.vehicle_plate = None
    # Drop Telegram link too — the user is gone.
    u.telegram_chat_id = None
    # Suspend so any in-flight session check on the next request fails.
    u.status = UserStatus.SUSPENDED


def _cancel_my_pending_and_accepted(s: Session, u: User) -> int:
    """Cancel every active booking where `u` is rider or driver. Returns
    the number of bookings that released a seat."""
    released = 0
    active = (BookingStatus.PENDING, BookingStatus.ACCEPTED)
    rows = s.exec(
        select(Booking).where(
            ((Booking.rider_id == u.id) | (Booking.driver_id == u.id)),
            Booking.status.in_(active),
        )
    ).all()
    now = datetime.now(timezone.utc)
    for b in rows:
        was_accepted = held_a_seat(b.status.value)
        b.status = BookingStatus.CANCELLED_BY_RIDER if b.rider_id == u.id else BookingStatus.CANCELLED_BY_DRIVER
        b.decided_at = now
        if was_accepted:
            inst = s.get(TripInstance, b.trip_instance_id)
            if inst is not None:
                inst.seats_taken = max(0, inst.seats_taken - 1)
                inst.locked = False
            released += 1
    # Future instances the user was driving: cancel those, too.
    trips = s.exec(select(Trip).where(Trip.driver_id == u.id)).all()
    for t in trips:
        future_insts = s.exec(
            select(TripInstance).where(
                TripInstance.trip_id == t.id,
                TripInstance.status == TripStatus.ACTIVE,
                TripInstance.depart_at > now,
            )
        ).all()
        for inst in future_insts:
            inst.status = TripStatus.CANCELLED
            inst.cancelled_at = now
            inst.cancelled_by_id = u.id
            # Drop every booking on this instance.
            bs = s.exec(
                select(Booking).where(Booking.trip_instance_id == inst.id)
            ).all()
            for b in bs:
                if b.status in active:
                    b.status = BookingStatus.CANCELLED_BY_DRIVER
                    b.decided_at = now
    return released


@router.get("/delete", response_class=HTMLResponse)
def delete_form(
    request: Request, session: Session = Depends(get_session),
) -> HTMLResponse:
    lang = _lang(request)
    s = get_settings()
    me = current_user(request, session)
    if me is None:
        return RedirectResponse("/auth/signin", status_code=303)
    return HTMLResponse(
        render(
            "me/delete.html",
            lang=lang, settings=s, request=request, me=me,
            form_error=None,
        )
    )


@router.post("/delete")
def delete_submit(
    request: Request,
    confirm: str = Form(""),
    csrf_token: str | None = Form(None),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    lang = _lang(request)
    s = get_settings()
    require_csrf(request, csrf_token)
    me = current_user(request, session)
    if me is None:
        return RedirectResponse("/auth/signin", status_code=303)
    if confirm.strip() != "DELETE":
        return HTMLResponse(
            render(
                "me/delete.html",
                lang=lang, settings=s, request=request, me=me,
                form_error="me.delete.bad_confirm",
            ),
            status_code=400,
        )
    # Capture pre-anon label for the audit row.
    label = me.full_name
    _cancel_my_pending_and_accepted(session, me)
    _anonymize_user(session, me)
    audit_write(
        session,
        actor_id=me.id,
        actor_label=label,
        action="user.delete_self",
        target_kind="user",
        target_id=me.id,
        target_label=label,
        detail="user self-deleted; PII scrubbed, bookings cancelled",
    )
    session.commit()
    # Sign the user out.
    resp = RedirectResponse("/", status_code=303)
    clear_session(resp)
    return resp
