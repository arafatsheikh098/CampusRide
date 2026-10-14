"""Phone normalization table-driven tests (M1 acceptance A3)."""
from __future__ import annotations

import pytest

from app.phone import PhoneError, normalize


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("01712345678", "+8801712345678"),
        ("+8801712345678", "+8801712345678"),
        ("8801712345678", "+8801712345678"),
        ("017-1234-5678", "+8801712345678"),
        ("017 1234 5678", "+8801712345678"),
        ("  01712345678  ", "+8801712345678"),
        ("+880 1712 345 678", "+8801712345678"),
        # Different operator prefixes
        ("01912345678", "+8801912345678"),
        ("01812345678", "+8801812345678"),
        ("01512345678", "+8801512345678"),
    ],
)
def test_normalize_accepts(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",                # empty
        "01212345678",     # wrong operator prefix
        "0171234567",      # too short
        "017123456789",    # too long
        "+880171234567",   # too short
        "+88017123456789", # too long
        "abc",             # not a number
        "+1 555 1234",     # foreign
        "02-8870000",      # landline-style
        None,              # type: ignore[arg-type]
    ],
)
def test_normalize_rejects(raw) -> None:
    with pytest.raises(PhoneError):
        normalize(raw)  # type: ignore[arg-type]
