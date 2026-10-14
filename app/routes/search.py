"""Search UI (F5).

The matching logic lives in `app.matching` so it can be tested without
the web stack. This route just hydrates `MatchRequest` and `TripSnapshot`
rows, runs `match()`, and renders the result list.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from sqlmodel import Session, select

from ..auth import current_user
from ..config import get_settings
from ..db import get_session
from ..main import render
from ..matching import (
    REASON_EXACT_PICKUP,
    REASON_SAME_GROUP_PICKUP,
    MatchRequest,
    TripSnapshot,
    match,
)
from ..models.place import Place
from ..models.trip import Trip, TripInstance, TripStatus
from ..models.trust import Block
from ..models.user import User, UserStatus

router = APIRouter(prefix="/search", tags=["search"])

_DHAKA = ZoneInfo("Asia/Dhaka")


def _lang(request: Request) -> str:
    s = get_settings()
    c = request.cookies.get("cr_lang")
    return c if c in s.supported_languages else s.default_lang


def _reason_key(reason: str) -> str:
    if reason == REASON_EXACT_PICKUP:
        return "search.reason.exact_pickup"
    if reason == REASON_SAME_GROUP_PICKUP:
        return "search.reason.same_group_pickup"
    return ""


def _approved_member(request: Request, session: Session) -> User | None:
    me = current_user(request, session)
    if me is None or me.status != UserStatus.APPROVED:
        return None
    return me


def _load_blocks(session: Session, rider_id: int) -> list[tuple[int, int]]:
    rows = session.exec(
        select(Block).where(
            (Block.blocker_id == rider_id) | (Block.blocked_id == rider_id)
        )
    ).all()
    return [(b.blocker_id, b.blocked_id) for b in rows]


def _load_trip_snapshots(
    session: Session, *, to_place_id: int, rider_id: int,
) -> list[TripSnapshot]:
    """Return one snapshot per ACTIVE instance whose trip's to_place matches."""
    instances = session.exec(
        select(TripInstance).where(
            TripInstance.status == TripStatus.ACTIVE,
        )
    ).all()
    out: list[TripSnapshot] = []
    for inst in instances:
        trip = session.get(Trip, inst.trip_id)
        if trip is None:
            continue
        if trip.to_place_id != to_place_id:
            continue
        from_place = session.get(Place, trip.from_place_id)
        group = from_place.group_label if from_place is not None else ""
        out.append(
            TripSnapshot(
                trip_id=trip.id,
                instance_id=inst.id,
                driver_id=trip.driver_id,
                from_place_id=trip.from_place_id,
                from_place_group=group,
                to_place_id=trip.to_place_id,
                earliest_departure=trip.earliest_departure,
                latest_departure=trip.latest_departure,
                seats_offered=trip.seats_offered,
                seats_taken=inst.seats_taken,
                women_only=trip.women_only,
                is_active=(inst.status == TripStatus.ACTIVE),
            )
        )
    return out


@router.get("", response_class=HTMLResponse)
def search_form(
    request: Request, session: Session = Depends(get_session),
) -> HTMLResponse:
    me = _approved_member(request, session)
    if me is None:
        return HTMLResponse(
            render(
                "404.html",
                lang=_lang(request),
                settings=get_settings(),
                request=request,
            ),
            status_code=404,
        )
    places = session.exec(
        select(Place).order_by(Place.group_label, Place.name)
    ).all()
    return HTMLResponse(
        render(
            "search/form.html",
            lang=_lang(request),
            settings=get_settings(),
            request=request,
            me=me,
            places=places,
            results=None,
            form_values={},
            form_error=None,
        )
    )


@router.post("", response_class=HTMLResponse)
def search_submit(
    request: Request,
    from_place_id: int = Form(...),
    to_place_id: int = Form(...),
    earliest: str = Form(...),
    latest: str = Form(...),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    me = _approved_member(request, session)
    s = get_settings()
    lang = _lang(request)
    places = session.exec(
        select(Place).order_by(Place.group_label, Place.name)
    ).all()
    form_values = {
        "from_place_id": from_place_id,
        "to_place_id": to_place_id,
        "earliest": earliest,
        "latest": latest,
    }
    if from_place_id == to_place_id:
        return HTMLResponse(
            render(
                "search/form.html",
                lang=lang, settings=s, request=request, me=me, places=places,
                results=None,
                form_values=form_values,
                form_error="trips.err.same_place",
            ),
            status_code=400,
        )
    try:
        earliest_dt = datetime.fromisoformat(earliest).replace(tzinfo=_DHAKA)
        latest_dt = datetime.fromisoformat(latest).replace(tzinfo=_DHAKA)
    except ValueError:
        return HTMLResponse(
            render(
                "search/form.html",
                lang=lang, settings=s, request=request, me=me, places=places,
                results=None,
                form_values=form_values,
                form_error="form.invalid_datetime",
            ),
            status_code=400,
        )
    if latest_dt < earliest_dt:
        return HTMLResponse(
            render(
                "search/form.html",
                lang=lang, settings=s, request=request, me=me, places=places,
                results=None,
                form_values=form_values,
                form_error="trips.err.window_reversed",
            ),
            status_code=400,
        )
    from_place = session.get(Place, from_place_id)
    to_place = session.get(Place, to_place_id)
    if from_place is None or to_place is None:
        return HTMLResponse(
            render(
                "search/form.html",
                lang=lang, settings=s, request=request, me=me, places=places,
                results=None,
                form_values=form_values,
                form_error="form.invalid_date",
            ),
            status_code=400,
        )
    snapshots = _load_trip_snapshots(
        session, to_place_id=to_place_id, rider_id=me.id,
    )
    blocks = _load_blocks(session, me.id)
    req = MatchRequest(
        rider_id=me.id,
        from_place_id=from_place.id,
        from_place_group=from_place.group_label,
        to_place_id=to_place.id,
        earliest=earliest_dt.astimezone(timezone.utc),
        latest=latest_dt.astimezone(timezone.utc),
        riders_women_only_eligible=bool(me.women_only_eligible),
    )
    matches = match(
        req,
        snapshots,
        blocks,
        time_tolerance_minutes=s.time_match_tolerance_minutes,
        women_only_enabled=bool(s.women_only_trips),
    )
    # Index snapshots by instance_id for the seat count.
    seats_by_instance = {s_.instance_id: s_.seats_taken for s_ in snapshots}
    # Hydrate results with trip / place info for the template.
    results = []
    for m in matches:
        trip = session.get(Trip, m.trip_id)
        if trip is None:
            continue
        fp = session.get(Place, trip.from_place_id)
        tp = session.get(Place, trip.to_place_id)
        results.append({
            "trip": trip,
            "instance_id": m.instance_id,
            "from_place": fp,
            "to_place": tp,
            "reason_key": _reason_key(m.reason),
            "seats_left": trip.seats_offered - seats_by_instance.get(m.instance_id, 0),
        })
    return HTMLResponse(
        render(
            "search/form.html",
            lang=lang, settings=s, request=request, me=me, places=places,
            results=results,
            form_values=form_values,
            form_error=None,
        )
    )
