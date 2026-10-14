"""Small helper for safe relative redirects.

Always validates that a `next`-style value is a same-origin path. Anything
else (absolute URL, scheme-relative, malformed) collapses to "/".
"""
from __future__ import annotations


def safe_next(value: str | None, default: str = "/") -> str:
    if not value:
        return default
    v = value.strip()
    # Reject scheme-relative ("//evil.com") and absolute URLs.
    if v.startswith("//") or "://" in v or v.startswith("\\"):
        return default
    # Must start with a single "/".
    if not v.startswith("/"):
        return default
    # Disallow backslashes and CR/LF (header injection).
    if any(ch in v for ch in ("\r", "\n", "\\")):
        return default
    return v
