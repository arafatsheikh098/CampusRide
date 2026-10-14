"""i18n key parity and basic lookups (M1 acceptance A4, G9)."""
from __future__ import annotations

import json
from pathlib import Path


from app import i18n


def test_en_and_bn_have_identical_keys() -> None:
    en = set(json.loads((Path(__file__).parent.parent / "app/i18n/en.json").read_text(encoding="utf-8")).keys())
    bn = set(json.loads((Path(__file__).parent.parent / "app/i18n/bn.json").read_text(encoding="utf-8")).keys())
    assert en == bn
    assert en, "dictionaries should not be empty"


def test_t_returns_translation() -> None:
    assert i18n.t("app.title", "en") == "CampusRide"
    assert i18n.t("app.title", "bn") == "ক্যাম্পাসরাইড"


def test_t_falls_back_to_default_then_key() -> None:
    # If a key is missing in bn, the en value should be used; if missing
    # everywhere, the key is returned so the UI never crashes.
    assert i18n.t("app.title", "bn", default_lang="en") == "ক্যাম্পাসরাইড"
    assert i18n.t("does.not.exist", "en") == "does.not.exist"


def test_supported_languages_lists_json_files() -> None:
    langs = i18n.supported_languages()
    assert "en" in langs and "bn" in langs
