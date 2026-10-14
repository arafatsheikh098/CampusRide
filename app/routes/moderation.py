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
from ..models.booking import Booking, BookingStatus
from ..models.place import Place
from ..models.trip import Trip, TripInstance, TripStatus
from ..models.trust import PostTripCheck, PostTripAnswer, Report
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
    reports = session.exec(
        select(Report).where(Report.resolved == False).order_by(Report.created_at)  # noqa: E712
    ).all()
    last_minute = session.exec(
        select(Booking).where(Booking.last_minute_cancel == True).order_by(  # noqa: E712
            Booking.decided_at.desc()
        )
    ).all()
    post_trip_problems = session.exec(
        select(PostTripCheck).where(
            PostTripCheck.answer == PostTripAnswer.PROBLEM,
        ).order_by(PostTripCheck.created_at)
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
            reports=reports,
            last_minute=last_minute,
            post_trip_problems=post_trip_problems,
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


# --- Place management (F2) -----------------------------------------------

_PLACE_KINDS = {"gate", "hall", "department", "pickup", "neighbourhood"}


@router.get("/places", response_class=HTMLResponse)
def places(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    me = current_user(request, session)
    if me is None or me.role.value != "moderator" or me.status != UserStatus.APPROVED:
        raise HTTPException(status_code=404)
    lang = _lang(request)
    s = get_settings()
    places = session.exec(select(Place).order_by(Place.group_label, Place.name)).all()
    return HTMLResponse(
        render(
            "moderation/places.html",
            lang=lang, settings=s, request=request, me=me,
            places=places, error=None,
        )
    )


@router.post("/places")
def places_create(
    request: Request,
    name: str = Form(...),
    group_label: str = Form(...),
    kind: str = Form(...),
    csrf_token: str | None = Form(None),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    me = current_user(request, session)
    if me is None or me.role.value != "moderator" or me.status != UserStatus.APPROVED:
        raise HTTPException(status_code=404)
    require_csrf(request, csrf_token)
    lang = _lang(request)
    s = get_settings()
    name = name.strip()[:80]
    group_label = group_label.strip()[:80]
    kind = kind.strip().lower()
    error = None
    if not name or not group_label:
        error = "places.err.empty"
    elif kind not in _PLACE_KINDS:
        error = "places.err.kind"
    elif session.exec(select(Place).where(Place.name == name)).first() is not None:
        error = "places.err.dup"
    if error is None:
        session.add(
            Place(name=name, group_label=group_label, kind=kind, created_at=datetime.now(timezone.utc))
        )
        write(
            session,
            actor_id=me.id, actor_label=me.full_name,
            action="place.create",
            target_kind="place", target_id=0, target_label=name,
        )
        session.commit()
        return RedirectResponse("/moderation/places", status_code=303)
    places = session.exec(select(Place).order_by(Place.group_label, Place.name)).all()
    return HTMLResponse(
        render(
            "moderation/places.html",
            lang=lang, settings=s, request=request, me=me,
            places=places, error=error, form_values={"name": name, "group_label": group_label, "kind": kind},
        ),
        status_code=400,
    )


@router.post("/places/{place_id}/delete")
def places_delete(
    place_id: int,
    request: Request,
    csrf_token: str | None = Form(None),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    me = current_user(request, session)
    if me is None or me.role.value != "moderator" or me.status != UserStatus.APPROVED:
        raise HTTPException(status_code=404)
    require_csrf(request, csrf_token)
    target = session.get(Place, place_id)
    if target is not None:
        write(
            session,
            actor_id=me.id, actor_label=me.full_name,
            action="place.delete",
            target_kind="place", target_id=target.id, target_label=target.name,
        )
        session.delete(target)
        session.commit()
    return RedirectResponse("/moderation/places", status_code=303)


# --- Driver verification (F3) and women-only eligibility (F5) -----------

def _drive_audit_actor(me: User) -> tuple[int, str]:
    return me.id, me.full_name


@router.post("/accounts/{user_id}/driver-verify")
def driver_verify(
    user_id: int,
    request: Request,
    vehicle_description: str = Form(...),
    vehicle_plate: str = Form(""),
    csrf_token: str | None = Form(None),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    me = current_user(request, session)
    require_moderator(me)
    require_csrf(request, csrf_token)
    target = session.get(User, user_id)
    if target is None or target.status != UserStatus.APPROVED:
        raise HTTPException(status_code=404)
    desc = vehicle_description.strip()[:80]
    plate = vehicle_plate.strip()[:40] or None
    if not desc:
        raise HTTPException(status_code=400, detail="vehicle_required")
    target.driver_verified = True
    target.driver_verified_at = datetime.now(timezone.utc)
    target.vehicle_description = desc
    target.vehicle_plate = plate
    actor_id, actor_label = _drive_audit_actor(me)
    write(
        session,
        actor_id=actor_id, actor_label=actor_label,
        action="user.driver_verify",
        target_kind="user", target_id=target.id, target_label=target.full_name,
    )
    session.commit()
    return RedirectResponse(f"/moderation/accounts/{target.id}", status_code=303)


@router.post("/accounts/{user_id}/driver-revoke")
def driver_revoke(
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
    if not target.driver_verified:
        return RedirectResponse(f"/moderation/accounts/{target.id}", status_code=303)
    target.driver_verified = False
    target.driver_verified_at = None
    target.vehicle_description = None
    target.vehicle_plate = None
    actor_id, actor_label = _drive_audit_actor(me)
    write(
        session,
        actor_id=actor_id, actor_label=actor_label,
        action="user.driver_revoke",
        target_kind="user", target_id=target.id, target_label=target.full_name,
    )
    session.commit()
    # Future unbooked instances are hidden by the matching engine because
    # the driver flag is now False. Past booking state is left untouched.
    return RedirectResponse(f"/moderation/accounts/{target.id}", status_code=303)


@router.post("/accounts/{user_id}/women-only-grant")
def women_only_grant(
    user_id: int,
    request: Request,
    csrf_token: str | None = Form(None),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    me = current_user(request, session)
    require_moderator(me)
    require_csrf(request, csrf_token)
    target = session.get(User, user_id)
    if target is None or target.status != UserStatus.APPROVED:
        raise HTTPException(status_code=404)
    if not get_settings().women_only_trips:
        # Feature disabled: silently ignore.
        return RedirectResponse(f"/moderation/accounts/{target.id}", status_code=303)
    if target.women_only_eligible:
        return RedirectResponse(f"/moderation/accounts/{target.id}", status_code=303)
    target.women_only_eligible = True
    actor_id, actor_label = _drive_audit_actor(me)
    write(
        session,
        actor_id=actor_id, actor_label=actor_label,
        action="user.women_only_grant",
        target_kind="user", target_id=target.id, target_label=target.full_name,
    )
    session.commit()
    return RedirectResponse(f"/moderation/accounts/{target.id}", status_code=303)


@router.post("/accounts/{user_id}/women-only-revoke")
def women_only_revoke(
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
    if not target.women_only_eligible:
        return RedirectResponse(f"/moderation/accounts/{target.id}", status_code=303)
    target.women_only_eligible = False
    actor_id, actor_label = _drive_audit_actor(me)
    write(
        session,
        actor_id=actor_id, actor_label=actor_label,
        action="user.women_only_revoke",
        target_kind="user", target_id=target.id, target_label=target.full_name,
    )
    session.commit()
    return RedirectResponse(f"/moderation/accounts/{target.id}", status_code=303)


@router.get("/accounts/{user_id}", response_class=HTMLResponse)
def account_detail(
    user_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    me = current_user(request, session)
    if me is None or me.role.value != "moderator" or me.status != UserStatus.APPROVED:
        raise HTTPException(status_code=404)
    target = session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404)
    lang = _lang(request)
    s = get_settings()
    return HTMLResponse(
        render(
            "moderation/account.html",
            lang=lang, settings=s, request=request, me=me, target=target,
        )
    )


# --- Reports, last-minute cancellations, post-trip problems ---------------


@router.post("/reports/{report_id}/resolve")
def reports_resolve(
    report_id: int,
    request: Request,
    csrf_token: str | None = Form(None),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    me = current_user(request, session)
    require_moderator(me)
    require_csrf(request, csrf_token)
    rep = session.get(Report, report_id)
    if rep is None:
        raise HTTPException(status_code=404)
    if rep.resolved:
        return RedirectResponse(f"/moderation/reports/{rep.id}", status_code=303)
    rep.resolved = True
    write(
        session,
        actor_id=me.id, actor_label=me.full_name,
        action="report.resolve",
        target_kind="report", target_id=rep.id,
        target_label=rep.reason.value,
    )
    session.commit()
    return RedirectResponse(f"/moderation/reports/{rep.id}", status_code=303)


@router.get("/reports/{report_id}", response_class=HTMLResponse)
def report_detail(
    report_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    me = current_user(request, session)
    if me is None or me.role.value != "moderator" or me.status != UserStatus.APPROVED:
        raise HTTPException(status_code=404)
    rep = session.get(Report, report_id)
    if rep is None:
        raise HTTPException(status_code=404)
    reporter = session.get(User, rep.reporter_id)
    target_user = session.get(User, rep.target_user_id) if rep.target_user_id else None
    target_trip = session.get(Trip, rep.target_trip_id) if rep.target_trip_id else None
    lang = _lang(request)
    s = get_settings()
    return HTMLResponse(
        render(
            "moderation/report.html",
            lang=lang, settings=s, request=request, me=me,
            report=rep, reporter=reporter,
            target_user=target_user, target_trip=target_trip,
        )
    )


@router.post("/trips/{trip_id}/remove")
def trips_remove(
    trip_id: int,
    request: Request,
    csrf_token: str | None = Form(None),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    me = current_user(request, session)
    require_moderator(me)
    require_csrf(request, csrf_token)
    trip = session.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(status_code=404)
    instances = session.exec(
        select(TripInstance).where(TripInstance.trip_id == trip.id)
    ).all()
    bookings = session.exec(
        select(Booking).where(
            Booking.driver_id == trip.driver_id,
            Booking.status.in_(
                [BookingStatus.PENDING, BookingStatus.ACCEPTED]
            ),
        )
    ).all()
    inst_ids = {i.id for i in instances}
    related = [b for b in bookings if b.trip_instance_id in inst_ids]
    # Cancel every future booked instance and free its seat.
    for inst in instances:
        if inst.status == TripStatus.ACTIVE:
            inst.status = TripStatus.CANCELLED
            inst.cancelled_at = datetime.now(timezone.utc)
            inst.cancelled_by_id = me.id
    for b in related:
        was_accepted = b.status == BookingStatus.ACCEPTED
        b.status = BookingStatus.CANCELLED_BY_DRIVER
        b.decided_at = datetime.now(timezone.utc)
        b.last_minute_cancel = True
        if was_accepted:
            inst = next((i for i in instances if i.id == b.trip_instance_id), None)
            if inst is not None:
                inst.seats_taken = max(0, inst.seats_taken - 1)
                inst.locked = False
    write(
        session,
        actor_id=me.id, actor_label=me.full_name,
        action="trip.remove",
        target_kind="trip", target_id=trip.id,
        target_label=f"#{trip.id}",
        detail=f"driver_id={trip.driver_id} affected_bookings={len(related)}",
    )
    session.commit()
    return RedirectResponse("/moderation", status_code=303)


@router.post("/post_trip/{check_id}/resolve")
def post_trip_resolve(
    check_id: int,
    request: Request,
    csrf_token: str | None = Form(None),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    me = current_user(request, session)
    require_moderator(me)
    require_csrf(request, csrf_token)
    check = session.get(PostTripCheck, check_id)
    if check is None:
        raise HTTPException(status_code=404)
    write(
        session,
        actor_id=me.id, actor_label=me.full_name,
        action="post_trip.resolve",
        target_kind="post_trip_check", target_id=check.id,
        target_label=f"#{check.id}",
    )
    # No DB field for handled; the audit row is the record.
    session.commit()
    return RedirectResponse("/moderation", status_code=303)

