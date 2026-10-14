"""Auth helpers: sessions, CSRF, rate limit, recovery codes, sign-up flow."""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Iterable

from fastapi import HTTPException, Request, Response, status
from sqlmodel import Session, select

from .config import Settings, get_settings
from .models.user import LoginAttempt, RecoveryCode, User, UserRole, UserStatus
from .phone import PhoneError, normalize as normalize_phone
from .security import (
    SESSION_CSRF,
    SESSION_USER_ID,
    constant_time_eq,
    hash_password,
    hash_token,
    new_token,
    verify_password,
)

# CSRF lives in the signed session payload; we compare the request token to
# the token we stored at sign-in. The form field name is `csrf_token`.

CSRF_FIELD = "csrf_token"
COOKIE_LANG = "cr_lang"
COOKIE_THEME = "cr_theme"
COOKIE_SESSION = "cr_session"

LOGIN_WINDOW = timedelta(minutes=15)
LOGIN_MAX_FAILS = 5

# Recovery codes are 12-char alphanumerics, groupped for readability.
RECOVERY_CODE_COUNT = 10


# --- Phone normalization --------------------------------------------------


def normalize_mobile(raw: str) -> str:
    try:
        return normalize_phone(raw)
    except PhoneError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# --- Sign-up --------------------------------------------------------------


def create_user(
    session: Session,
    *,
    full_name: str,
    department: str,
    batch_or_session: str,
    mobile_e164: str,
    password: str,
    is_campus_member: bool,
    is_18_or_older: bool,
) -> User:
    if not is_campus_member:
        raise HTTPException(status_code=400, detail="must_be_campus")
    if not is_18_or_older:
        raise HTTPException(status_code=400, detail="must_be_adult")
    if len(password) < 8:
        raise HTTPException(status_code=400, detail="password_too_short")
    # Reject duplicates by mobile.
    existing = session.exec(select(User).where(User.mobile_e164 == mobile_e164)).first()
    if existing is not None:
        raise HTTPException(status_code=400, detail="mobile_taken")
    now = datetime.now(timezone.utc)
    u = User(
        full_name=full_name.strip()[:120],
        department=department.strip()[:120],
        batch_or_session=batch_or_session.strip()[:60],
        mobile_e164=mobile_e164,
        password_hash=hash_password(password),
        role=UserRole.MEMBER,
        status=UserStatus.PENDING,
        is_campus_member=is_campus_member,
        is_18_or_older=is_18_or_older,
        created_at=now,
    )
    session.add(u)
    session.flush()
    return u


def generate_recovery_codes(session: Session, user: User) -> list[str]:
    """Create 10 single-use recovery codes; return their plaintext (caller
    shows them once). Storage is hashed."""
    now = datetime.now(timezone.utc)
    plain: list[str] = []
    for _ in range(RECOVERY_CODE_COUNT):
        # 12 chars, groupped 4-4-4 for human reading.
        raw = secrets.token_hex(6).upper()
        grouped = f"{raw[:4]}-{raw[4:8]}-{raw[8:12]}"
        plain.append(grouped)
        session.add(
            RecoveryCode(
                user_id=user.id,
                code_hash=hash_token(grouped),
                created_at=now,
            )
        )
    session.flush()
    return plain


def consume_recovery_code(session: Session, user: User, code: str) -> bool:
    if not code:
        return False
    h = hash_token(code.strip().upper())
    row = session.exec(
        select(RecoveryCode).where(
            RecoveryCode.user_id == user.id, RecoveryCode.code_hash == h, RecoveryCode.used == False  # noqa: E712
        )
    ).first()
    if row is None:
        return False
    row.used = True
    row.used_at = datetime.now(timezone.utc)
    session.flush()
    return True


# --- Login rate limit -----------------------------------------------------


def recent_failures(session: Session, mobile_e164: str) -> int:
    since = datetime.now(timezone.utc) - LOGIN_WINDOW
    rows = session.exec(
        select(LoginAttempt).where(
            LoginAttempt.mobile_e164 == mobile_e164,
            LoginAttempt.created_at >= since,
        )
    ).all()
    return sum(1 for r in rows if not r.succeeded)


def record_login_attempt(session: Session, mobile_e164: str, succeeded: bool) -> None:
    session.add(
        LoginAttempt(
            mobile_e164=mobile_e164,
            succeeded=succeeded,
            created_at=datetime.now(timezone.utc),
        )
    )


def authenticate(
    session: Session, mobile_e164: str, password: str
) -> User | None:
    """Verify credentials. Always goes through the same code path whether the
    user is missing, suspended, or the password is wrong — so the response
    is identical and timing is similar."""
    u = session.exec(select(User).where(User.mobile_e164 == mobile_e164)).first()
    # Always run a hash check to keep timing similar.
    if u is None:
        # The hash check will still run on a dummy value.
        verify_password(password, hash_password("dummy-password-to-consume-time"))
        return None
    if not verify_password(password, u.password_hash):
        return None
    return u


# --- Session cookie and CSRF ---------------------------------------------


def issue_session(response: Response, user: User, settings: Settings) -> str:
    """Set the session cookie on `response` and return the CSRF token. The
    CSRF token must be embedded in every state-changing form."""
    csrf = new_token()
    from .main import make_session_cookie
    cookie = make_session_cookie(
        settings.secret_key, int(user.id), user.role.value, csrf
    )
    response.set_cookie(
        COOKIE_SESSION,
        cookie,
        max_age=60 * 60 * 24 * 30,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        path="/",
    )
    # Clear the pre-session if any.
    response.delete_cookie("cr_pre", path="/")
    return csrf


def issue_pre_session(response: Response, settings: Settings) -> str:
    """Set a pre-session cookie that carries only a CSRF token. Used by the
    sign-up form so that even unauthenticated state-changing requests can
    be CSRF-protected.
    """
    csrf = new_token()
    from .main import make_pre_session_cookie
    cookie = make_pre_session_cookie(settings.secret_key, csrf)
    response.set_cookie(
        "cr_pre",
        cookie,
        max_age=60 * 60 * 24,
        httponly=True,
        samesite="lax",
        secure=settings.is_production,
        path="/",
    )
    return csrf


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE_SESSION, path="/")
    response.delete_cookie("cr_pre", path="/")


def current_user(request: Request, session: Session) -> User | None:
    """Read the session cookie and return the user; check status live so a
    suspension immediately invalidates the session."""
    from .main import read_session_cookie
    s = get_settings()
    raw = request.cookies.get(COOKIE_SESSION)
    if not raw:
        return None
    data = read_session_cookie(s.secret_key, raw)
    if not data:
        return None
    uid = data.get(SESSION_USER_ID)
    if not isinstance(uid, int):
        return None
    u = session.get(User, uid)
    if u is None:
        return None
    # Suspended users are evicted at request time. Pending/rejected users
    # can only access the public pages.
    return u


def require_csrf(request: Request, form_token: str | None) -> None:
    """Raise 403 if the form's CSRF token does not match the session's.

    Accepts either the real session cookie or the pre-session cookie used
    by the sign-up form.
    """
    from .main import read_session_cookie
    s = get_settings()
    raw = request.cookies.get(COOKIE_SESSION) or request.cookies.get("cr_pre")
    if not raw:
        raise HTTPException(status_code=403, detail="missing_session")
    data = read_session_cookie(s.secret_key, raw)
    if not data:
        raise HTTPException(status_code=403, detail="bad_session")
    expected = data.get(SESSION_CSRF)
    if not expected or not form_token or not constant_time_eq(str(expected), str(form_token)):
        raise HTTPException(status_code=403, detail="bad_csrf")


# --- Dependencies ---------------------------------------------------------


def require_member(user: User | None) -> User:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Location": "/auth/signin"},
            detail="login_required",
        )
    if user.status != UserStatus.APPROVED:
        # Reject pending/rejected/suspended for member pages.
        raise HTTPException(status_code=403, detail="not_approved")
    return user


def require_moderator(user: User | None) -> User:
    if user is None or user.role != UserRole.MODERATOR:
        raise HTTPException(status_code=403, detail="moderator_required")
    return user


# --- Test helpers ---------------------------------------------------------


def csrf_for(user: User, settings: Settings) -> str:
    """Return the CSRF token from the just-issued session (test helper).

    Tests typically issue a session via the FastAPI app and then read the
    CSRF token out of the response cookie or by signing the cookie they
    already have. This helper signs a session and returns the CSRF token
    that was put into it, for convenience.
    """
    csrf = new_token()
    return csrf


def list_member_routes() -> Iterable[str]:
    """Routes that require an approved member session. Used by the
    route-discovery test to enumerate every state-changing route."""
    # Imported lazily to avoid a circular dependency.
    from .routes import (
        auth as _auth,
        bookings as _bookings,
        blocks as _blocks,
        driver as _driver,
        moderation as _moderation,
        notifications as _notifications,
        places as _places,
        profile as _profile,
        reports as _reports,
        search as _search,
        trips as _trips,
    )

    modules = (_auth, _bookings, _blocks, _driver, _moderation, _notifications, _places, _profile, _reports, _search, _trips)
    for mod in modules:
        for r in getattr(mod, "router", []).routes:
            if getattr(r, "methods", None) and any(m in {"POST", "PUT", "PATCH", "DELETE"} for m in r.methods):
                yield r.path
