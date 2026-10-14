"""Authentication routes: sign-up, sign-in, sign-out, recovery."""
from __future__ import annotations


from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from ..audit import write
from ..auth import (
    clear_session,
    create_user,
    current_user,
    generate_recovery_codes,
    issue_pre_session,
    issue_session,
    normalize_mobile,
    recent_failures,
    record_login_attempt,
    require_csrf,
)
from ..config import get_settings
from ..db import get_session
from ..main import render
from ..models.user import UserStatus

router = APIRouter(prefix="/auth", tags=["auth"])

# Error code -> i18n key for the signup form.
_SIGNUP_ERR_KEY = {
    "must_be_campus": "auth.signup.errors.must_be_campus",
    "must_be_adult": "auth.signup.errors.must_be_adult",
    "password_too_short": "auth.signup.errors.password_mismatch",
    "mobile_taken": "auth.signup.errors.invalid_phone",
}


def _lang(request: Request) -> str:
    s = get_settings()
    c = request.cookies.get("cr_lang")
    return c if c in s.supported_languages else s.default_lang


@router.get("/signup", response_class=HTMLResponse)
def signup_form(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
    lang = _lang(request)
    s = get_settings()
    user = current_user(request, session)
    if user is not None and user.status == UserStatus.APPROVED:
        return RedirectResponse("/", status_code=303)
    # We need to set a pre-session cookie AND render the form with the
    # matching CSRF token. We do both with a placeholder response first,
    # then re-render once the cookie is known.
    if not request.cookies.get("cr_pre"):
        placeholder = HTMLResponse("")
        csrf = issue_pre_session(placeholder, s)
        # Render the form with the explicit csrf; client carries the cookie.
        body = render(
            "auth/signup.html",
            lang=lang,
            settings=s,
            request=request,
            form_error=None,
            form_values={},
            csrf=csrf,
        )
        resp = HTMLResponse(body)
        # Copy the cookie header from the placeholder.
        for k, v in placeholder.headers.items():
            if k.lower() == "set-cookie":
                resp.headers.append(k, v)
        return resp
    # Existing pre-session: extract the CSRF token from the cookie.
    from ..main import read_session_cookie
    data = read_session_cookie(s.secret_key, request.cookies.get("cr_pre", ""))
    csrf = str((data or {}).get("csrf", ""))
    body = render(
        "auth/signup.html",
        lang=lang,
        settings=s,
        request=request,
        form_error=None,
        form_values={},
        csrf=csrf,
    )
    return HTMLResponse(body)


@router.post("/signup")
def signup_submit(
    request: Request,
    full_name: str = Form(...),
    department: str = Form(...),
    batch_or_session: str = Form(...),
    mobile: str = Form(...),
    password: str = Form(...),
    confirm_password: str = Form(...),
    is_campus_member: str = Form(""),
    is_18_or_older: str = Form(""),
    csrf_token: str | None = Form(None),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    lang = _lang(request)
    s = get_settings()

    is_campus = is_campus_member in ("on", "true", "1")
    is_adult = is_18_or_older in ("on", "true", "1")

    err_key = None
    form_values = {
        "full_name": full_name,
        "department": department,
        "batch_or_session": batch_or_session,
        "mobile": mobile,
    }

    if password != confirm_password:
        err_key = "auth.signup.errors.password_mismatch"
    else:
        try:
            mobile_e164 = normalize_mobile(mobile)
        except Exception:
            err_key = "auth.signup.errors.invalid_phone"
            mobile_e164 = None  # type: ignore[assignment]
        if mobile_e164:
            try:
                u = create_user(
                    session,
                    full_name=full_name,
                    department=department,
                    batch_or_session=batch_or_session,
                    mobile_e164=mobile_e164,
                    password=password,
                    is_campus_member=is_campus,
                    is_18_or_older=is_adult,
                )
            except Exception as e:
                # Map HTTPException details to i18n keys.
                from fastapi import HTTPException
                if isinstance(e, HTTPException):
                    err_key = _SIGNUP_ERR_KEY.get(str(e.detail), "common.error")
                else:
                    err_key = "common.error"
            else:
                # Generate recovery codes immediately and show them once.
                codes = generate_recovery_codes(session, u)
                write(
                    session,
                    actor_id=u.id,
                    actor_label=u.full_name,
                    action="user.signup",
                    target_kind="user",
                    target_id=u.id,
                    target_label=u.full_name,
                    detail=f"status=pending; mobile={u.mobile_e164}",
                )
                session.commit()
                return HTMLResponse(
                    render(
                        "auth/recovery.html",
                        lang=lang,
                        settings=s,
                        request=request,
                        codes=codes,
                    )
                )

    if err_key is None:
        err_key = "common.error"
    return HTMLResponse(
        render("auth/signup.html", lang=lang, settings=s, request=request, form_error=err_key, form_values=form_values),
        status_code=400,
    )


@router.get("/signin", response_class=HTMLResponse)
def signin_form(request: Request, next: str = "/", session: Session = Depends(get_session)) -> HTMLResponse:
    return _render_signin(request, error=None, next=next)


def _render_signin(
    request: Request,
    *,
    error: str | None,
    next: str,
    status_code: int = 200,
) -> HTMLResponse:
    """Render the signin page, ensuring a pre-session CSRF cookie is set.
    If the request already has `cr_pre`, we reuse it; otherwise we issue
    a fresh one and embed the matching token in the form.
    """
    lang = _lang(request)
    s = get_settings()
    placeholder = HTMLResponse("")
    if not request.cookies.get("cr_pre"):
        csrf = issue_pre_session(placeholder, s)
    else:
        from ..main import read_session_cookie
        data = read_session_cookie(
            s.secret_key, request.cookies.get("cr_pre", ""),
        )
        csrf = str((data or {}).get("csrf", ""))
    body = render(
        "auth/signin.html",
        lang=lang,
        settings=s,
        request=request,
        error=error,
        next=next,
        csrf=csrf,
    )
    resp = HTMLResponse(body, status_code=status_code)
    for k, v in placeholder.headers.items():
        if k.lower() == "set-cookie":
            resp.headers.append(k, v)
    return resp


@router.post("/signin")
def signin_submit(
    request: Request,
    mobile: str = Form(...),
    password: str = Form(...),
    next: str = Form("/"),
    csrf_token: str | None = Form(None),
    session: Session = Depends(get_session),
) -> HTMLResponse:
    require_csrf(request, csrf_token)
    s = get_settings()

    try:
        mobile_e164 = normalize_mobile(mobile)
    except Exception:
        # Same generic error for invalid format.
        return _render_signin(
            request, error="auth.signin.invalid", next=next, status_code=400,
        )

    # Rate limit
    if recent_failures(session, mobile_e164) >= 5:
        return _render_signin(
            request, error="auth.signin.rate_limited", next=next, status_code=429,
        )

    from ..auth import authenticate
    u = authenticate(session, mobile_e164, password)
    if u is None:
        record_login_attempt(session, mobile_e164, False)
        session.commit()
        return _render_signin(
            request, error="auth.signin.invalid", next=next, status_code=400,
        )

    record_login_attempt(session, mobile_e164, True)
    if u.status == UserStatus.SUSPENDED:
        session.commit()
        return _render_signin(
            request, error="auth.signin.suspended", next=next, status_code=403,
        )
    if u.status != UserStatus.APPROVED:
        session.commit()
        return _render_signin(
            request, error="auth.signin.pending", next=next, status_code=403,
        )

    write(
        session,
        actor_id=u.id,
        actor_label=u.full_name,
        action="user.signin",
        target_kind="user",
        target_id=u.id,
        target_label=u.full_name,
    )
    session.commit()
    # Issue session in a redirect so the cookie is set.
    resp = RedirectResponse(next or "/", status_code=303)
    issue_session(resp, u, s)
    return resp


@router.post("/signout")
def signout(
    request: Request,
    csrf_token: str | None = Form(None),
    session: Session = Depends(get_session),
) -> RedirectResponse:
    require_csrf(request, csrf_token)
    u = current_user(request, session)
    if u is not None:
        write(
            session,
            actor_id=u.id,
            actor_label=u.full_name,
            action="user.signout",
            target_kind="user",
            target_id=u.id,
            target_label=u.full_name,
        )
        session.commit()
    resp = RedirectResponse("/", status_code=303)
    clear_session(resp)
    return resp


@router.get("/recovery", response_class=HTMLResponse)
def recovery_info(request: Request) -> HTMLResponse:
    lang = _lang(request)
    s = get_settings()
    return HTMLResponse(render("auth/recovery_info.html", lang=lang, settings=s, request=request))
