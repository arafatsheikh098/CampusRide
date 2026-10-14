"""FastAPI app factory and /health route.

The factory builds the app from settings; tests build an app with a SQLite
in-memory engine and a stubbed heartbeat.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncIterator

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import BadSignature, URLSafeTimedSerializer
from jinja2 import Environment, FileSystemLoader, pass_context, select_autoescape
from sqlmodel import Session, select

from .config import Settings, get_settings
from .db import get_engine, get_session
from .i18n import t as _t
from .models.heartbeat import Heartbeat
from .security import (
    SESSION_CSRF,
    SESSION_PRE,
    SESSION_ROLE,
    SESSION_USER_ID,
    assert_safe_secret_key,
)
from .timezone import app_now

# --- Jinja environment -----------------------------------------------------

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def _jinja_t(key: str, lang: str = "en") -> str:
    return _t(key, lang, default_lang=get_settings().default_lang)


_env.globals["t"] = _jinja_t
_env.filters["t"] = _jinja_t


def render(template: str, /, **ctx) -> str:
    # Provide safe defaults so child templates can reference these without
    # every route having to pass them.
    ctx.setdefault("me", None)
    ctx.setdefault("csrf", "")
    ctx.setdefault("form_values", {})
    ctx.setdefault("form_error", None)
    return _env.get_template(template).render(**ctx)


def _csrf_from_request(request: Request) -> str:
    """Return the CSRF token stored in the user's session cookie (or in the
    pre-session cookie used by the sign-up form)."""
    raw = request.cookies.get(COOKIE_NAME) or request.cookies.get("cr_pre")
    if not raw:
        return ""
    s = get_settings()
    data = read_session_cookie(s.secret_key, raw)
    if not data:
        return ""
    return str(data.get(SESSION_CSRF) or "")


@pass_context
def csrf_token(ctx) -> str:
    """Read the CSRF token from the current request's session cookies.
    Returns "" if there is no request or no session. Routes can also
    pass `csrf_token="..."` in the render context to override this.
    """
    req = ctx.get("request")
    if req is None:
        return ""
    return _csrf_from_request(req)


# Backwards-compatible name. New code should use `csrf_token()`.
_env.globals["csrf_token"] = csrf_token
_env.globals["csrf"] = csrf_token


# --- Session cookie helpers -----------------------------------------------

_SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days
COOKIE_NAME = "cr_session"


def _serializer(secret: str) -> URLSafeTimedSerializer:
    # Use a derived HMAC key so that rotating the SECRET_KEY invalidates
    # every existing session, but the cookie payload itself is not raw-keyed.
    derived = (secret + ":campusride").encode("utf-8")
    return URLSafeTimedSerializer(derived, salt="campusride-session")


def make_session_cookie(secret: str, user_id: int, role: str, csrf: str) -> str:
    s = _serializer(secret)
    return s.dumps(
        {SESSION_USER_ID: user_id, SESSION_ROLE: role, SESSION_CSRF: csrf},
    )


def make_pre_session_cookie(secret: str, csrf: str) -> str:
    s = _serializer(secret)
    return s.dumps({SESSION_PRE: True, SESSION_CSRF: csrf})


def read_session_cookie(secret: str, value: str) -> dict | None:
    if not value:
        return None
    try:
        data = _serializer(secret).loads(value, max_age=_SESSION_MAX_AGE)
    except BadSignature:
        return None
    if not isinstance(data, dict):
        return None
    return data


# Backwards-compatible re-export of the pre-session key.
SESSION_PRE_KEY = SESSION_PRE


# --- /health --------------------------------------------------------------


def _db_alive() -> bool:
    try:
        with Session(get_engine()) as s:
            s.exec(select(1))
        return True
    except Exception:
        return False


def _worker_heartbeat_age_seconds() -> float | None:
    try:
        with Session(get_engine()) as s:
            rows = s.exec(select(Heartbeat).order_by(Heartbeat.last_seen.desc())).all()
            if not rows:
                return None
            last = rows[0].last_seen
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            return (datetime.now(timezone.utc) - last).total_seconds()
    except Exception:
        return None


# --- App factory ----------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    assert_safe_secret_key()
    # Optionally run the heartbeat worker in this process. Tests turn this
    # off so they don't spawn background threads.
    worker_task = None
    if app.state.settings.run_worker_in_process:
        import asyncio
        from .worker import run_async

        async def _loop() -> None:
            await asyncio.to_thread(run_async)

        worker_task = asyncio.create_task(_loop())
    try:
        yield
    finally:
        if worker_task is not None:
            worker_task.cancel()
            try:
                await worker_task
            except Exception:
                pass


def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or get_settings()

    app = FastAPI(title="CampusRide", lifespan=_lifespan)
    app.state.settings = s

    # Static files: vendored HTMX, CSS and any later static assets.
    static_dir = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/health", include_in_schema=False)
    def health() -> JSONResponse:
        ok_db = _db_alive()
        age = _worker_heartbeat_age_seconds()
        healthy = ok_db and (age is not None and age <= 120)
        body = {
            "ok": healthy,
            "db": ok_db,
            "worker": {
                "heartbeat_age_seconds": age,
                "healthy": age is not None and age <= 120,
            },
            "app": {
                "env": s.app_env,
                "campus": s.campus_name,
                "tz": s.campus_timezone,
            },
            "now": app_now(s).isoformat(),
        }
        return JSONResponse(body, status_code=200 if healthy else 503)

    @app.get("/", include_in_schema=False)
    def home(request: Request, session: Session = Depends(get_session)) -> HTMLResponse:
        lang = _resolve_lang(request, s)
        from .auth import current_user
        me = current_user(request, session)
        return HTMLResponse(
            render("home.html", lang=lang, settings=s, request=request, me=me),
        )

    @app.exception_handler(404)
    async def _not_found(request: Request, exc):  # type: ignore[no-untyped-def]
        lang = _resolve_lang(request, s)
        return HTMLResponse(render("404.html", lang=lang, settings=s, request=request), status_code=404)

    @app.exception_handler(500)
    async def _server_error(request: Request, exc):  # type: ignore[no-untyped-def]
        lang = _resolve_lang(request, s)
        return HTMLResponse(render("500.html", lang=lang, settings=s, request=request), status_code=500)

    # Routers are attached by later milestones. The factory stays small.
    _attach_routers(app, s)
    _attach_security_headers(app, s)

    return app


def _resolve_lang(request: Request, s: Settings) -> str:
    cookie = request.cookies.get("cr_lang")
    if cookie and cookie in s.supported_languages:
        return cookie
    return s.default_lang


def _attach_routers(app: FastAPI, s: Settings) -> None:
    """Import and attach routers lazily. We try each in turn so partial
    milestones still boot (e.g. M1 with no routers attached)."""
    from .routes import auth as auth_routes  # noqa: F401
    from .routes import moderation as moderation_routes  # noqa: F401
    from .routes import places as places_routes  # noqa: F401
    from .routes import driver as driver_routes  # noqa: F401
    from .routes import trips as trips_routes  # noqa: F401
    from .routes import search as search_routes  # noqa: F401
    from .routes import bookings as bookings_routes  # noqa: F401
    from .routes import trusted_contact as trusted_contact_routes  # noqa: F401
    from .routes import blocks as blocks_routes  # noqa: F401
    from .routes import reports as reports_routes  # noqa: F401
    from .routes import notifications as notifications_routes  # noqa: F401
    from .routes import telegram as telegram_routes  # noqa: F401
    from .routes import policy as policy_routes  # noqa: F401
    from .routes import profile as profile_routes  # noqa: F401

    for mod in (
        auth_routes,
        moderation_routes,
        places_routes,
        driver_routes,
        trips_routes,
        search_routes,
        bookings_routes,
        trusted_contact_routes,
        blocks_routes,
        reports_routes,
        notifications_routes,
        telegram_routes,
        policy_routes,
        profile_routes,
    ):
        router = getattr(mod, "router", None)
        if router is not None:
            app.include_router(router)


def _attach_security_headers(app: FastAPI, s: Settings) -> None:
    """Security headers (F10). The CSP forbids inline scripts so all dynamic
    behaviour must come from vendored HTMX and the small JS in app/static."""

    @app.middleware("http")
    async def _headers(request, call_next):  # type: ignore[no-untyped-def]
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        # The app does not need camera, mic, geolocation, or payment. Lock
        # those down explicitly so a future injected script can't ask.
        resp.headers.setdefault(
            "Permissions-Policy",
            "camera=(), microphone=(), geolocation=(), payment=()",
        )
        csp = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "object-src 'none'; "
            "frame-ancestors 'none'; "
            "base-uri 'self'; "
            "form-action 'self'; "
            "upgrade-insecure-requests"
        )
        resp.headers.setdefault("Content-Security-Policy", csp)
        if request.url.scheme == "https":
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return resp


# --- WSGI/ASGI entry point -----------------------------------------------

app = create_app()
