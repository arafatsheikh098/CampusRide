"""Reports (F8).

A member can report another user or a trip with a short reason. The
report lands in the moderator queue. Every report is audit-logged.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from ..audit import write
from ..auth import current_user, require_csrf
from ..config import get_settings
from ..db import get_session
from ..main import render
from ..models.trip import Trip
from ..models.trust import Report, ReportReason
from ..models.user import User, UserStatus

router = APIRouter(prefix="/reports", tags=["reports"])


_REASONS = {r.value for r in ReportReason}


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


@router.get("/new", response_class=HTMLResponse)
def report_form(
    request: Request,
    target_user_id: int = 0,
    target_trip_id: int = 0,
    session: Session = Depends(get_session),
) -> HTMLResponse:
    me = _require_approved(current_user(request, session))
    lang = _lang(request)
    s = get_settings()
    return HTMLResponse(
        render(
            "reports/new.html",
            lang=lang, settings=s, request=request, me=me,
            target_user_id=target_user_id,
            target_trip_id=target_trip_id,
            reasons=list(ReportReason),
            form_error=None,
            form_values={},
        )
    )


@router.post("/new")
def report_submit(
    request: Request,
    reason: str = Form(...),
    note: str = Form(""),
    target_user_id: int = Form(0),
    target_trip_id: int = Form(0),
    csrf_token: str | None = Form(None),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    me = _require_approved(current_user(request, session))
    require_csrf(request, csrf_token)
    lang = _lang(request)
    s = get_settings()
    form_values = {
        "reason": reason, "note": note,
        "target_user_id": target_user_id,
        "target_trip_id": target_trip_id,
    }
    if reason not in _REASONS:
        return HTMLResponse(
            render("reports/new.html",
                   lang=lang, settings=s, request=request, me=me,
                   target_user_id=target_user_id,
                   target_trip_id=target_trip_id,
                   reasons=list(ReportReason),
                   form_error="reports.err.reason",
                   form_values=form_values),
            status_code=400,
        )
    if not target_user_id and not target_trip_id:
        return HTMLResponse(
            render("reports/new.html",
                   lang=lang, settings=s, request=request, me=me,
                   target_user_id=target_user_id,
                   target_trip_id=target_trip_id,
                   reasons=list(ReportReason),
                   form_error="reports.err.no_target",
                   form_values=form_values),
            status_code=400,
        )
    target_user = None
    target_trip = None
    if target_user_id:
        target_user = session.get(User, target_user_id)
        if target_user is None or target_user.id == me.id:
            return HTMLResponse(
                render("reports/new.html",
                       lang=lang, settings=s, request=request, me=me,
                       target_user_id=target_user_id,
                       target_trip_id=target_trip_id,
                       reasons=list(ReportReason),
                       form_error="reports.err.bad_user",
                       form_values=form_values),
                status_code=400,
            )
    if target_trip_id:
        target_trip = session.get(Trip, target_trip_id)
        if target_trip is None:
            return HTMLResponse(
                render("reports/new.html",
                       lang=lang, settings=s, request=request, me=me,
                       target_user_id=target_user_id,
                       target_trip_id=target_trip_id,
                       reasons=list(ReportReason),
                       form_error="reports.err.bad_trip",
                       form_values=form_values),
                status_code=400,
            )
    report = Report(
        reporter_id=me.id,
        target_user_id=target_user.id if target_user else None,
        target_trip_id=target_trip.id if target_trip else None,
        reason=ReportReason(reason),
        note=note.strip()[:400] or None,
        created_at=_now_utc(),
        resolved=False,
    )
    session.add(report)
    session.flush()
    write(
        session,
        actor_id=me.id, actor_label=me.full_name,
        action="report.create",
        target_kind="report", target_id=report.id,
        target_label=reason,
        detail=(
            f"user={target_user.id if target_user else '-'} "
            f"trip={target_trip.id if target_trip else '-'}"
        ),
    )
    session.commit()
    return RedirectResponse(
        url="/bookings?reported=1", status_code=303,
    )
