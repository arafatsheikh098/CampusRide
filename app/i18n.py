"""Tiny i18n helper. Two JSON dictionaries with identical keys.

The `t(key, lang)` function returns the translation; missing keys fall back
to the default language and then to the key itself so a missing translation
is visible in the UI rather than crashing the page.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Dict

_LOCK = threading.Lock()
_CACHE: Dict[str, Dict[str, str]] = {}


def _load(lang: str) -> Dict[str, str]:
    if lang in _CACHE:
        return _CACHE[lang]
    p = Path(__file__).parent / "i18n" / f"{lang}.json"
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
    with _LOCK:
        _CACHE[lang] = data
    return data


def t(key: str, lang: str, default_lang: str = "en") -> str:
    """Look up `key` in the chosen language; fall back to default; then to key."""
    if not key:
        return ""
    try:
        d = _load(lang)
    except FileNotFoundError:
        d = {}
    if key in d:
        return d[key]
    if lang != default_lang:
        try:
            d2 = _load(default_lang)
        except FileNotFoundError:
            return key
        return d2.get(key, key)
    return key


def keys(lang: str) -> set[str]:
    """Return the set of keys defined for `lang`. Used by the parity test."""
    return set(_load(lang).keys())


def supported_languages() -> list[str]:
    return sorted(p.stem for p in (Path(__file__).parent / "i18n").glob("*.json"))
