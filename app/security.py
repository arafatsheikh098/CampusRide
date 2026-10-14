"""Security helpers: passwords, sessions, CSRF, the production SECRET_KEY check."""
from __future__ import annotations

import hashlib
import hmac
import secrets
from typing import Final

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from . import config as _config  # looked up by attribute so tests can monkeypatch

_PH = PasswordHasher()

# Tokens used for sessions, CSRF and trusted-contact links. ≥128 bits.
TOKEN_BYTES: Final[int] = 32

# Keys for the signed session cookie. Centralised so routes don't reach into
# the config by name.
SESSION_USER_ID: Final[str] = "uid"
SESSION_ROLE: Final[str] = "role"
SESSION_CSRF: Final[str] = "csrf"
SESSION_CREATED: Final[str] = "iat"
# Pre-session: a signed cookie that carries only a CSRF token, used to
# protect the sign-up form before the user exists. Routes that allow
# unauthenticated users must check CSRF against this cookie.
SESSION_PRE: Final[str] = "pre"

# The session cookie is signed with itsdangerous.URLSafeTimedSerializer.
DEFAULT_SECRET: Final[str] = "change-me-to-a-long-random-string-at-least-32-chars"


def hash_password(plain: str) -> str:
    return _PH.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return _PH.verify(hashed, plain)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def needs_rehash(hashed: str) -> bool:
    try:
        return _PH.check_needs_rehash(hashed)
    except Exception:
        return False


def new_token() -> str:
    """A URL-safe token of at least 128 bits (32 bytes -> 43 base64url chars)."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """SHA-256 of a token. Used to store recovery codes and trusted-contact
    links at rest — only the hash is kept."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def assert_safe_secret_key() -> None:
    """Refuse to start in production with the placeholder SECRET_KEY.

    Called from the app factory and the worker entry point. Tests skip it
    by setting APP_ENV=development or providing a real secret.
    """
    s = _config.get_settings()
    if s.is_production and (not s.secret_key or s.secret_key == DEFAULT_SECRET or len(s.secret_key) < 32):
        raise RuntimeError(
            "Refusing to start: SECRET_KEY is the default or too short in production. "
            "Set a long random SECRET_KEY in the environment."
        )
