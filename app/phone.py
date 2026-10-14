"""Bangladesh mobile number validation and normalization.

The single source of truth for what a CampusRide mobile looks like. After
normalization, a number is stored as `+8801XXXXXXXXX` (E.164, 14 chars).

Accepts the user-typed forms from the spec:
  - 01712345678
  - +8801712345678
  - 8801712345678
  - 017-1234-5678

Rejects 01212345678, landline-style numbers and bad lengths.
"""
from __future__ import annotations

import re
from typing import Final

# Bangladesh mobile numbers (post-2018 11-digit plan): operator prefix 13/14/15/16/17/18/19.
# 11 digits starting with 01, e.g. 01712345678.
_BD_LOCAL: Final[re.Pattern[str]] = re.compile(r"^0(1[3-9])\d{8}$")
# Country code with optional +, e.g. 8801712345678 or +8801712345678.
_BD_INTL: Final[re.Pattern[str]] = re.compile(r"^\+?880(1[3-9])\d{8}$")
# Same as _BD_LOCAL but tolerates spaces, dashes and parentheses between groups.
_BD_LOCAL_LOOSE: Final[re.Pattern[str]] = re.compile(
    r"^0?\s*\(?1[3-9]\)?[\s\-]?\d{4}[\s\-]?\d{4}$"
)


class PhoneError(ValueError):
    """Raised when a phone number cannot be normalized."""


def normalize(raw: str) -> str:
    """Normalize a Bangladesh mobile number to E.164 (`+8801XXXXXXXXX`).

    Raises PhoneError on any other input. Whitespace and common separators
    are tolerated; the algorithm is deterministic.
    """
    if raw is None:
        raise PhoneError("phone is required")
    s = str(raw).strip()
    if not s:
        raise PhoneError("phone is required")

    # Strip spaces, dashes, parentheses for tolerance.
    compact = re.sub(r"[\s\-\(\)]", "", s)

    # Tightest path: full E.164 or 880-prefixed.
    m = _BD_INTL.match(compact)
    if m:
        return f"+880{m.group(1)}{compact[-8:]}"

    # Local form with leading 0: 01XXXXXXXXX.
    if _BD_LOCAL.match(compact):
        # 01XXXXXXXXX -> +8801XXXXXXXXX (drop the leading 0, prepend +880)
        return f"+880{compact[1:]}"

    # Country code without plus: 880XXXXXXXXXX.
    if re.match(r"^880(1[3-9])\d{8}$", compact):
        return f"+{compact}"

    raise PhoneError("not a valid Bangladesh mobile number")


def is_valid(raw: str) -> bool:
    try:
        normalize(raw)
        return True
    except PhoneError:
        return False
