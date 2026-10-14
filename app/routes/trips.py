"""Trip posting, detail and instance cancellation (F4).

Only driver-verified members can post or edit. Series edits touch only
future unbooked instances; past instances and any instance with seats
booked (`locked=True`) are never rewritten.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from ..auth import current_user, require_csrf
from ..config import get_settings
from ..db import get_session
from ..main import render
from ..models.booking import Booking, BookingStatus
from ..models.place import Place
from ..models.trip import RecurrenceKind, Trip, TripInstance, TripStatus
from ..models.user import User, UserStatus
from ..notifications import notify_trip_cancelled, notify_trip_removed  # noqa: F401
from ..recurrence import (
    generate_series,
)
from ..trip_validation import validate_trip

router = APIRouter(prefix="/trips", tags=["trips"])

_DHAKA = ZoneInfo("Asia/Dhaka")


def _lang(request: Request) -> str:
    s = get_settings()
    c = request.cookies.get("cr_lang")
    return c if c in s.supported_languages else s.default_lang


def _parse_local(s: str) -> datetime:
    """Parse a datetime-local string from a form into a tz-aware Asia/Dhaka datetime."""
    return datetime.fromisoformat(s).replace(tzinfo=_DHAKA)


def _parse_date(s: str):
    return datetime.strptime(s, "%Y-%m-%d").date()


def _weekday_mask(items) -> int:
    """Items are string weekday numbers ('0'..'6')."""
    mask = 0
    for x in items or ():
        try:
            i = int(x)
        except (TypeError, ValueError):
            continue
        if 0 <= i <= 6:
            mask |= 1 << i
    return mask


def _now_local() -> datetime:
    return datetime.now(_DHAKA)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _require_approved(me: User | None) -> User:
    if me is None or me.status != UserStatus.APPROVED:
        raise HTTPException(status_code=404)
    return me


@router.get("", response_class=HTMLResponse)
def list_my_trips(
    request: Request, session: Session = Depends(get_session)
) -> HTMLResponse:
    me = _require_approved(current_user(request, session))
    lang = _lang(request)
    s = get_settings()
    trips = session.exec(
        select(Trip).where(Trip.driver_id == me.id).order_by(Trip.created_at.desc())
    ).all()
    return HTMLResponse(
        render(
            "trips/list.html",
            lang=lang, settings=s, request=request, me=me, trips=trips,
        )
    )


@router.get("/new", response_class=HTMLResponse)
def new_trip_form(
    request: Request, session: Session = Depends(get_session)
) -> HTMLResponse:
    me = _require_approved(current_user(request, session))
    if not me.driver_verified:
        # G5: only driver-verified members can post trips.
        raise HTTPException(status_code=404)
    lang = _lang(request)
    s = get_settings()
    places = session.exec(select(Place).order_by(Place.group_label, Place.name)).all()
    return HTMLResponse(
        render(
            "trips/new.html",
            lang=lang, settings=s, request=request, me=me, places=places,
        )
    )


@router.post("/new")
def new_trip_submit(
    request: Request,
    from_place_id: int = Form(...),
    to_place_id: int = Form(...),
    earliest: str = Form(...),
    latest: str = Form(...),
    seats: int = Form(...),
    cost_per_seat_paisa: int = Form(0),
    note: str = Form(""),
    recurrence_kind: str = Form("one_off"),
    weekdays: list[str] = Form([]),
    series_end: str = Form(""),
    women_only: str = Form(""),
    csrf_token: str | None = Form(None),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    me = _require_approved(current_user(request, session))
    if not me.driver_verified:
        raise HTTPException(status_code=404)
    require_csrf(request, csrf_token)
    s = get_settings()
    lang = _lang(request)
    places = session.exec(select(Place).order_by(Place.group_label, Place.name)).all()
    women_only_flag = women_only == "on"
    if women_only_flag and (not s.women_only_trips or not me.women_only_eligible):
        # Tampered input: silently turn off.
        women_only_flag = False
    # Parse
    try:
        earliest_dt = _parse_local(earliest)
        latest_dt = _parse_local(latest)
    except ValueError:
        return _render_new_error(
            request, me, lang, s, places, "form.invalid_datetime",
        )
    now_local = _now_local()
    if earliest_dt < now_local:
        return _render_new_error(
            request, me, lang, s, places, "form.past_departure",
        )
    horizon_end_local = now_local + timedelta(days=s.trip_horizon_days)
    if latest_dt > horizon_end_local:
        # Reject anything outside the rolling horizon.
        return _render_new_error(
            request, me, lang, s, places, "form.horizon",
        )
    series_end_date = None
    try:
        if recurrence_kind == "weekly":
            if not series_end:
                return _render_new_error(
                    request, me, lang, s, places, "series_end_required",
                )
            series_end_date = _parse_date(series_end)
    except ValueError:
        return _render_new_error(
            request, me, lang, s, places, "form.invalid_date",
        )
    err = validate_trip(
        from_place_id=from_place_id,
        to_place_id=to_place_id,
        earliest=earliest_dt, latest=latest_dt,
        seats=seats, cost_per_seat_paisa=cost_per_seat_paisa,
        note=note,
        recurrence_kind=recurrence_kind,
        weekdays_mask=_weekday_mask(weekdays),
        series_start=earliest_dt.date(),
        series_end=series_end_date,
        cost_cap_paisa=s.cost_per_seat_cap_paisa,
    )
    if err:
        return _render_new_error(request, me, lang, s, places, err)
    # Save the series and its instances.
    now_utc = _now_utc()
    series_start_date = earliest_dt.date()
    if recurrence_kind == "one_off":
        rkind = RecurrenceKind.ONE_OFF
        mask = 0
        series_end_db = None
    else:
        rkind = RecurrenceKind.WEEKLY
        mask = _weekday_mask(weekdays)
        series_end_db = datetime.combine(series_end_date, time(0, 0))
    trip = Trip(
        driver_id=me.id,
        from_place_id=from_place_id, to_place_id=to_place_id,
        earliest_departure=earliest_dt.astimezone(timezone.utc),
        latest_departure=latest_dt.astimezone(timezone.utc),
        seats_offered=seats,
        cost_per_seat_paisa=cost_per_seat_paisa,
        note=note.strip() or None,
        women_only=women_only_flag,
        recurrence_kind=rkind,
        weekdays_mask=mask,
        series_end_date=series_end_db,
        series_start_date=datetime.combine(series_start_date, time(0, 0)),
        created_at=now_utc, updated_at=now_utc,
    )
    session.add(trip)
    session.flush()
    # Generate dated instances.
    departs = generate_series(
        recurrence_kind=rkind.value,
        series_start_local=series_start_date,
        series_end_local=series_end_date,
        weekdays_mask=mask,
        earliest_local=earliest_dt,
        horizon_end_local=horizon_end_local,
    )
    for depart_at in departs:
        session.add(
            TripInstance(
                trip_id=trip.id,
                depart_at=depart_at.astimezone(timezone.utc),
                seats_taken=0,
                status=TripStatus.ACTIVE,
            )
        )
    session.commit()
    return RedirectResponse(f"/trips/{trip.id}", status_code=303)


def _render_new_error(request, me, lang, s, places, error):
    return HTMLResponse(
        render(
            "trips/new.html",
            lang=lang, settings=s, request=request, me=me, places=places,
            form_error=error,
        ),
        status_code=400,
    )


@router.get("/{trip_id}", response_class=HTMLResponse)
def trip_detail(
    trip_id: int,
    request: Request,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    me = _require_approved(current_user(request, session))
    lang = _lang(request)
    s = get_settings()
    trip = session.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(status_code=404)
    from_place = session.get(Place, trip.from_place_id)
    to_place = session.get(Place, trip.to_place_id)
    driver = session.get(User, trip.driver_id)
    instances = session.exec(
        select(TripInstance)
        .where(TripInstance.trip_id == trip_id)
        .order_by(TripInstance.depart_at)
    ).all()
    return HTMLResponse(
        render(
            "trips/detail.html",
            lang=lang, settings=s, request=request, me=me,
            trip=trip, from_place=from_place, to_place=to_place,
            driver=driver, instances=instances,
        )
    )


@router.post("/{trip_id}/instances/{instance_id}/cancel")
def cancel_instance(
    trip_id: int,
    instance_id: int,
    request: Request,
    reason: str = Form(""),
    csrf_token: str | None = Form(None),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    me = _require_approved(current_user(request, session))
    require_csrf(request, csrf_token)
    trip = session.get(Trip, trip_id)
    instance = session.get(TripInstance, instance_id)
    if trip is None or instance is None or instance.trip_id != trip.id:
        raise HTTPException(status_code=404)
    if trip.driver_id != me.id:
        raise HTTPException(status_code=403)
    if instance.status != TripStatus.ACTIVE:
        return RedirectResponse(f"/trips/{trip.id}", status_code=303)
    instance.status = TripStatus.CANCELLED
    instance.cancelled_at = _now_utc()
    instance.cancelled_by_id = me.id
    # Notify the riders.
    bookings = session.exec(
        select(Booking).where(
            Booking.trip_instance_id == instance.id,
            Booking.status != BookingStatus.CANCELLED,
        )
    ).all()
    riders = []
    for b in bookings:
        u = session.get(User, b.rider_id)
        if u is not None:
            riders.append(u)
    if riders:
        notify_trip_cancelled(
            session,
            instance_id=instance.id,
            by_user=me,
            recipients=riders,
        )
    session.commit()
    return RedirectResponse(f"/trips/{trip.id}", status_code=303)
