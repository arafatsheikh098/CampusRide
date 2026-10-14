"""Trusted-contact read-only page (F7).

A rider with an accepted booking on a trip instance can generate a
read-only link. The link is a >=128-bit random token; only its SHA-256
hash is stored. The public route accepts the raw token, hashes it, and
looks up the row. The page reveals route, time, driver first name and
vehicle description only. No login required, no live tracking, no
contacts. The link expires `grace_minutes` after the trip's depart time.
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
from ..models.booking import Booking, BookingStatus
from ..models.place import Place
from ..models.trip import Trip, TripInstance
from ..models.trust import TrustedContactLink
from ..models.user import User, UserStatus
from ..reveal import (
    make_trusted_token,
    trusted_link_expiry,
    is_trusted_link_active,
)
from ..security import hash_token

router = APIRouter(tags=["trusted_contact"])


def _lang(request: Request) -> str:
    s = get_settings()
    c = request.cookies.get("cr_lang")
    return c if c in s.supported_languages else s.default_lang


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


@router.post(
    "/trips/{trip_id}/instances/{instance_id}/trusted-link"
)
def trusted_link_create(
    trip_id: int,
    instance_id: int,
    request: Request,
    csrf_token: str | None = Form(None),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    me = current_user(request, session)
    if me is None or me.status != UserStatus.APPROVED:
        raise HTTPException(status_code=404)
    require_csrf(request, csrf_token)
    trip = session.get(Trip, trip_id)
    instance = session.get(TripInstance, instance_id)
    if trip is None or instance is None or instance.trip_id != trip.id:
        raise HTTPException(status_code=404)
    booking = session.exec(
        select(Booking).where(
            Booking.trip_instance_id == instance.id,
            Booking.rider_id == me.id,
        )
    ).first()
    if booking is None or booking.status != BookingStatus.ACCEPTED:
        raise HTTPException(status_code=403, detail="not_accepted")
    raw, token_hash = make_trusted_token()
    expires_at = trusted_link_expiry(instance.depart_at, _now_utc())
    link = TrustedContactLink(
        booking_id=booking.id,
        trip_instance_id=instance.id,
        created_by_id=me.id,
        token_hash=token_hash,
        created_at=_now_utc(),
        expires_at=expires_at,
    )
    session.add(link)
    session.flush()
    write(
        session,
        actor_id=me.id, actor_label=me.full_name,
        action="trusted_link.create",
        target_kind="booking", target_id=booking.id,
        target_label=f"#{booking.id}",
        detail=f"link expires {expires_at.isoformat()}",
    )
    session.commit()
    # Pass the raw token to the booking page once via a query param; the
    # audit row never sees the raw token.
    return RedirectResponse(
        url=f"/bookings?trusted_token={raw}", status_code=303,
    )


@router.get("/trusted/{token}", response_class=HTMLResponse)
def trusted_link_view(
    token: str,
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    """Public, no-auth page. Reveals only route, time, driver first
    name and vehicle description."""
    if not token or len(token) < 16:
        raise HTTPException(status_code=404)
    token_hash = hash_token(token)
    row = session.exec(
        select(TrustedContactLink).where(
            TrustedContactLink.token_hash == token_hash,
        )
    ).first()
    lang = _lang(request)
    s = get_settings()
    if row is None:
        return HTMLResponse(
            render("trusted_contact/view.html",
                   lang=lang, settings=s, request=request,
                   payload=None, status="invalid"),
            status_code=404,
        )
    if not is_trusted_link_active(row.expires_at, _now_utc()):
        return HTMLResponse(
            render("trusted_contact/view.html",
                   lang=lang, settings=s, request=request,
               payload=None, status="expired"),
            status_code=410,
        )
    instance = session.get(TripInstance, row.trip_instance_id)
    trip = session.get(Trip, instance.trip_id) if instance else None
    driver = session.get(User, trip.driver_id) if trip else None
    from_place = session.get(Place, trip.from_place_id) if trip else None
    to_place = session.get(Place, trip.to_place_id) if trip else None
    if instance is None or trip is None or driver is None:
        return HTMLResponse(
            render("trusted_contact/view.html",
                   lang=lang, settings=s, request=request,
                   payload=None, status="invalid"),
            status_code=404,
        )
    from_label = (
        f"{from_place.name} ({from_place.group_label})"
        if from_place is not None else ""
    )
    to_label = (
        f"{to_place.name} ({to_place.group_label})"
        if to_place is not None else ""
    )
    payload = {
        "from": from_label,
        "to": to_label,
        "depart_at": instance.depart_at,
        "driver_first_name": (driver.full_name or "").split()[0],
        "vehicle_description": driver.vehicle_description or "",
    }
    return HTMLResponse(
        render("trusted_contact/view.html",
               lang=lang, settings=s, request=request,
               payload=payload, status="ok"),
    )
