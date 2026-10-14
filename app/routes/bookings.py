"""Seat booking flow (F6).

* Riders POST `/bookings/new` to ask for a seat on a trip instance.
* Drivers POST `/bookings/{id}/accept` or `/decline`.
* Either side can cancel; cancelled-by-rider / cancelled-by-driver /
  declined bookings release the seat.
* Cancellations inside the configured last-minute window mark the
  booking `last_minute_cancel=True` (visible to moderators).
* Every state change is audit-logged and (where appropriate)
  notifies the other party via the notifications interface.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from ..audit import write as audit_write
from ..auth import current_user, require_csrf
from ..booking import (
    BOOKING_REASON_MAX_LEN,
    MAX_ACTIVE_BOOKINGS_PER_DAY,
    MAX_PENDING_REQUESTS,
    held_a_seat,
    is_active,
    is_blocked,
    is_last_minute,
    validate_reason,
)
from ..config import get_settings
from ..db import get_session
from ..main import render
from ..models.booking import Booking, BookingStatus
from ..models.trip import Trip, TripInstance, TripStatus
from ..models.trust import Block, PostTripAnswer, PostTripCheck
from ..models.user import User, UserStatus
from ..notifications import (
    notify_booking_cancelled,
    notify_booking_decision,
    notify_booking_request,
)
from ..reveal import post_trip_check_available

router = APIRouter(prefix="/bookings", tags=["bookings"])


def _lang(request: Request) -> str:
    s = get_settings()
    c = request.cookies.get("cr_lang")
    return c if c in s.supported_languages else s.default_lang


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _approved_member_or_none(request: Request, session: Session) -> User | None:
    me = current_user(request, session)
    if me is None or me.status != UserStatus.APPROVED:
        return None
    return me


def _instance_and_trip(
    session: Session, b: Booking,
) -> tuple[TripInstance | None, Trip | None]:
    inst = session.get(TripInstance, b.trip_instance_id)
    if inst is None:
        return None, None
    trip = session.get(Trip, inst.trip_id)
    return inst, trip


def _my_pending_count(session: Session, rider_id: int) -> int:
    rows = session.exec(
        select(Booking).where(
            Booking.rider_id == rider_id,
            Booking.status == BookingStatus.PENDING,
        )
    ).all()
    return len(rows)


def _my_active_on_day(
    session: Session, rider_id: int, depart_at: datetime,
) -> int:
    """How many of the rider's bookings on `depart_at.date()` are still
    active (pending or accepted)."""
    rows = session.exec(
        select(Booking).where(Booking.rider_id == rider_id)
    ).all()
    n = 0
    target_d = depart_at.date()
    inst_ids = [b.trip_instance_id for b in rows]
    if not inst_ids:
        return 0
    instances = session.exec(
        select(TripInstance).where(TripInstance.id.in_(inst_ids))
    ).all()
    by_id = {i.id: i for i in instances}
    for b in rows:
        if b.status not in (BookingStatus.PENDING, BookingStatus.ACCEPTED):
            continue
        inst = by_id.get(b.trip_instance_id)
        if inst is not None and inst.depart_at.date() == target_d:
            n += 1
    return n


def _blocks(session: Session, me_id: int) -> list[tuple[int, int]]:
    rows = session.exec(
        select(Block).where(
            (Block.blocker_id == me_id) | (Block.blocked_id == me_id)
        )
    ).all()
    return [(b.blocker_id, b.blocked_id) for b in rows]


@router.get("", response_class=HTMLResponse)
def list_my_bookings(
    request: Request, session: Session = Depends(get_session),
) -> HTMLResponse:
    me = _approved_member_or_none(request, session)
    s = get_settings()
    lang = _lang(request)
    if me is None:
        return HTMLResponse(
            render("404.html", lang=lang, settings=s, request=request),
            status_code=404,
        )
    bookings = session.exec(
        select(Booking).where(Booking.rider_id == me.id)
        .order_by(Booking.created_at.desc())
    ).all()
    instance_ids = {b.trip_instance_id for b in bookings}
    instances: dict[int, TripInstance] = {}
    if instance_ids:
        for inst in session.exec(
            select(TripInstance).where(TripInstance.id.in_(instance_ids))
        ).all():
            instances[inst.id] = inst
    trip_ids = {inst.trip_id for inst in instances.values()}
    trips: dict[int, Trip] = {}
    if trip_ids:
        for t in session.exec(
            select(Trip).where(Trip.id.in_(trip_ids))
        ).all():
            trips[t.id] = t
    driver_ids = {t.driver_id for t in trips.values()}
    drivers: dict[int, User] = {}
    if driver_ids:
        for u in session.exec(
            select(User).where(User.id.in_(driver_ids))
        ).all():
            drivers[u.id] = u
    # Post-trip check status per booking for this viewer.
    checks: dict[int, PostTripCheck] = {}
    for chk in session.exec(
        select(PostTripCheck).where(PostTripCheck.responder_id == me.id)
    ).all():
        checks[chk.booking_id] = chk
    trusted_token = request.query_params.get("trusted_token", "")
    reported = request.query_params.get("reported", "")
    return HTMLResponse(
        render(
            "bookings/list.html",
            lang=lang, settings=s, request=request, me=me,
            bookings=bookings, instances=instances, trips=trips,
            drivers=drivers, checks=checks,
            trusted_token=trusted_token, reported=reported,
        )
    )


@router.post("/new")
def create_booking(
    request: Request,
    trip_instance_id: int = Form(...),
    csrf_token: str | None = Form(None),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    me = _approved_member_or_none(request, session)
    if me is None:
        raise HTTPException(status_code=404)
    require_csrf(request, csrf_token)
    inst = session.get(TripInstance, trip_instance_id)
    if inst is None or inst.status != TripStatus.ACTIVE:
        raise HTTPException(status_code=404)
    trip = session.get(Trip, inst.trip_id)
    if trip is None:
        raise HTTPException(status_code=404)
    if trip.driver_id == me.id:
        raise HTTPException(status_code=403, detail="self_booking")
    if trip.women_only and not me.women_only_eligible:
        raise HTTPException(status_code=403, detail="not_women_only_eligible")
    pairs = _blocks(session, me.id)
    if is_blocked(me.id, trip.driver_id, pairs):
        raise HTTPException(status_code=403, detail="blocked")
    if trip.seats_offered - inst.seats_taken <= 0:
        raise HTTPException(status_code=409, detail="trip_full")
    if _my_pending_count(session, me.id) >= MAX_PENDING_REQUESTS:
        raise HTTPException(status_code=409, detail="pending_limit")
    if _my_active_on_day(session, me.id, inst.depart_at) >= MAX_ACTIVE_BOOKINGS_PER_DAY:
        raise HTTPException(status_code=409, detail="daily_limit")
    existing = session.exec(
        select(Booking).where(
            Booking.trip_instance_id == inst.id,
            Booking.rider_id == me.id,
        )
    ).first()
    if existing is not None and existing.status in (
        BookingStatus.PENDING, BookingStatus.ACCEPTED,
    ):
        raise HTTPException(status_code=409, detail="already_requested")
    now = _now_utc()
    b = Booking(
        trip_instance_id=inst.id,
        rider_id=me.id,
        driver_id=trip.driver_id,
        status=BookingStatus.PENDING,
        created_at=now,
    )
    session.add(b)
    session.flush()
    audit_write(
        session,
        actor_id=me.id, actor_label=me.full_name,
        action="booking.request",
        target_kind="booking", target_id=b.id,
        target_label=f"#{b.id}",
        detail=f"rider requested seat on instance #{inst.id} of trip #{trip.id}",
    )
    notify_booking_request(session, booking=b, trip=trip)
    session.commit()
    return RedirectResponse(url=f"/trips/{trip.id}", status_code=303)


def _load_booking_or_404(session: Session, booking_id: int) -> Booking:
    b = session.get(Booking, booking_id)
    if b is None:
        raise HTTPException(status_code=404)
    return b


@router.post("/{booking_id}/accept")
def accept_booking(
    booking_id: int,
    request: Request,
    csrf_token: str | None = Form(None),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    me = _approved_member_or_none(request, session)
    if me is None:
        raise HTTPException(status_code=404)
    require_csrf(request, csrf_token)
    b = _load_booking_or_404(session, booking_id)
    inst, trip = _instance_and_trip(session, b)
    if trip is None or inst is None:
        raise HTTPException(status_code=404)
    if trip.driver_id != me.id:
        raise HTTPException(status_code=403)
    if b.status != BookingStatus.PENDING:
        return RedirectResponse(url="/bookings", status_code=303)
    if inst.status != TripStatus.ACTIVE:
        raise HTTPException(status_code=409, detail="instance_inactive")
    if inst.seats_taken >= trip.seats_offered:
        raise HTTPException(status_code=409, detail="trip_full")
    inst.seats_taken += 1
    inst.locked = True
    b.status = BookingStatus.ACCEPTED
    b.decided_at = _now_utc()
    audit_write(
        session,
        actor_id=me.id, actor_label=me.full_name,
        action="booking.accept",
        target_kind="booking", target_id=b.id,
        target_label=f"#{b.id}",
        detail=f"driver accepted booking #{b.id} on instance #{inst.id}",
    )
    notify_booking_decision(session, booking=b, accepted=True)
    session.commit()
    return RedirectResponse(url=f"/trips/{trip.id}", status_code=303)


@router.post("/{booking_id}/decline")
def decline_booking(
    booking_id: int,
    request: Request,
    reason: str = Form(""),
    csrf_token: str | None = Form(None),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    me = _approved_member_or_none(request, session)
    if me is None:
        raise HTTPException(status_code=404)
    require_csrf(request, csrf_token)
    b = _load_booking_or_404(session, booking_id)
    inst, trip = _instance_and_trip(session, b)
    if inst is None or trip is None:
        raise HTTPException(status_code=404)
    if trip.driver_id != me.id:
        raise HTTPException(status_code=403)
    if b.status != BookingStatus.PENDING:
        return RedirectResponse(url="/bookings", status_code=303)
    err = validate_reason(reason)
    if err:
        raise HTTPException(status_code=400, detail=err)
    b.status = BookingStatus.DECLINED
    b.decided_at = _now_utc()
    if reason.strip():
        b.driver_cancel_reason = reason.strip()[:BOOKING_REASON_MAX_LEN]
    audit_write(
        session,
        actor_id=me.id, actor_label=me.full_name,
        action="booking.decline",
        target_kind="booking", target_id=b.id,
        target_label=f"#{b.id}",
        detail=f"driver declined booking #{b.id}",
    )
    notify_booking_decision(session, booking=b, accepted=False)
    session.commit()
    return RedirectResponse(url=f"/trips/{trip.id}", status_code=303)


@router.post("/{booking_id}/cancel")
def cancel_booking_by_rider(
    booking_id: int,
    request: Request,
    reason: str = Form(""),
    csrf_token: str | None = Form(None),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    me = _approved_member_or_none(request, session)
    s = get_settings()
    if me is None:
        raise HTTPException(status_code=404)
    require_csrf(request, csrf_token)
    b = _load_booking_or_404(session, booking_id)
    if b.rider_id != me.id:
        raise HTTPException(status_code=403)
    if not is_active(b.status.value):
        return RedirectResponse(url="/bookings", status_code=303)
    err = validate_reason(reason)
    if err:
        raise HTTPException(status_code=400, detail=err)
    inst, trip = _instance_and_trip(session, b)
    if inst is None:
        raise HTTPException(status_code=404)
    was_accepted = held_a_seat(b.status.value)
    now = _now_utc()
    last_minute = is_last_minute(
        inst.depart_at, now, s.last_minute_window_minutes,
    )
    b.status = BookingStatus.CANCELLED_BY_RIDER
    b.decided_at = now
    b.last_minute_cancel = last_minute
    if reason.strip():
        b.rider_cancel_reason = reason.strip()[:BOOKING_REASON_MAX_LEN]
    if was_accepted:
        inst.seats_taken = max(0, inst.seats_taken - 1)
        inst.locked = False
    audit_write(
        session,
        actor_id=me.id, actor_label=me.full_name,
        action="booking.cancel_rider",
        target_kind="booking", target_id=b.id,
        target_label=f"#{b.id}",
        detail=("last-minute" if last_minute else "in time"),
    )
    notify_booking_cancelled(session, booking=b, by_user=me)
    session.commit()
    return RedirectResponse(
        url=f"/trips/{trip.id if trip else 0}", status_code=303,
    )


@router.post("/{booking_id}/driver_cancel")
def cancel_booking_by_driver(
    booking_id: int,
    request: Request,
    reason: str = Form(""),
    csrf_token: str | None = Form(None),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    me = _approved_member_or_none(request, session)
    s = get_settings()
    if me is None:
        raise HTTPException(status_code=404)
    require_csrf(request, csrf_token)
    b = _load_booking_or_404(session, booking_id)
    if b.driver_id != me.id:
        raise HTTPException(status_code=403)
    if not is_active(b.status.value):
        return RedirectResponse(url="/bookings", status_code=303)
    err = validate_reason(reason)
    if err:
        raise HTTPException(status_code=400, detail=err)
    inst, trip = _instance_and_trip(session, b)
    if inst is None:
        raise HTTPException(status_code=404)
    was_accepted = held_a_seat(b.status.value)
    now = _now_utc()
    last_minute = is_last_minute(
        inst.depart_at, now, s.last_minute_window_minutes,
    )
    b.status = BookingStatus.CANCELLED_BY_DRIVER
    b.decided_at = now
    b.last_minute_cancel = last_minute
    if reason.strip():
        b.driver_cancel_reason = reason.strip()[:BOOKING_REASON_MAX_LEN]
    if was_accepted:
        inst.seats_taken = max(0, inst.seats_taken - 1)
        inst.locked = False
    audit_write(
        session,
        actor_id=me.id, actor_label=me.full_name,
        action="booking.cancel_driver",
        target_kind="booking", target_id=b.id,
        target_label=f"#{b.id}",
        detail=("last-minute" if last_minute else "in time"),
    )
    notify_booking_cancelled(session, booking=b, by_user=me)
    session.commit()
    return RedirectResponse(
        url=f"/trips/{trip.id if trip else 0}", status_code=303,
    )


@router.post("/{booking_id}/check")
def post_trip_check(
    booking_id: int,
    request: Request,
    answer: str = Form(...),
    note: str = Form(""),
    csrf_token: str | None = Form(None),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    """Both parties can answer the post-trip check after the trip time.
    The check is private; only "problem" answers surface to moderators."""
    me = _approved_member_or_none(request, session)
    if me is None:
        raise HTTPException(status_code=404)
    require_csrf(request, csrf_token)
    b = _load_booking_or_404(session, booking_id)
    if me.id not in (b.rider_id, b.driver_id):
        raise HTTPException(status_code=403)
    if answer not in ("ok", "problem"):
        raise HTTPException(status_code=400, detail="bad_answer")
    inst = session.get(TripInstance, b.trip_instance_id)
    if inst is None:
        raise HTTPException(status_code=404)
    if not post_trip_check_available(inst.depart_at, _now_utc()):
        raise HTTPException(status_code=400, detail="not_yet")
    existing = session.exec(
        select(PostTripCheck).where(
            PostTripCheck.booking_id == b.id,
            PostTripCheck.responder_id == me.id,
        )
    ).first()
    if existing is not None:
        return RedirectResponse("/bookings", status_code=303)
    check = PostTripCheck(
        booking_id=b.id,
        responder_id=me.id,
        answer=PostTripAnswer(answer),
        note=note.strip()[:400] or None,
        created_at=_now_utc(),
    )
    session.add(check)
    audit_write(
        session,
        actor_id=me.id, actor_label=me.full_name,
        action="post_trip.check",
        target_kind="booking", target_id=b.id,
        target_label=f"#{b.id}",
        detail=answer,
    )
    session.commit()
    return RedirectResponse("/bookings", status_code=303)
