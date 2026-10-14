"""Application configuration via pydantic-settings.

Settings are read from environment variables and a local `.env` file. The
default SECRET_KEY is a clearly fake placeholder; production refuses to start
with it (see `app.security.assert_safe_secret_key`).
"""
from __future__ import annotations

import re
from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- App ---
    app_env: str = "development"
    secret_key: str = Field(
        default="change-me-to-a-long-random-string-at-least-32-chars",
        description="Long random string. Required in production.",
    )
    database_url: str = "sqlite:///./campusride.db"

    # --- i18n ---
    default_lang: str = "en"
    supported_langs: str = "en,bn"

    # --- Campus ---
    campus_name: str = "North Campus"
    campus_timezone: str = "Asia/Dhaka"
    emergency_number: str = "999"
    member_cap: int = 200
    retention_days: int = 90
    trip_horizon_days: int = 14
    last_minute_window_minutes: int = 120
    time_match_tolerance_minutes: int = 15
    cost_per_seat_cap_paisa: int = 50000

    # --- Workers ---
    run_worker_in_process: bool = False
    heartbeat_interval_seconds: int = 30

    # --- Telegram (optional) ---
    telegram_bot_token: str | None = None
    telegram_webhook_secret: str | None = None

    # --- Safety features ---
    women_only_trips: bool = False

    # --- Demo ---
    demo_mode: bool = False

    @property
    def supported_languages(self) -> List[str]:
        return [s.strip() for s in self.supported_langs.split(",") if s.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @field_validator("member_cap", "retention_days", "trip_horizon_days")
    @classmethod
    def _positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("must be positive")
        return v

    @field_validator("trip_horizon_days")
    @classmethod
    def _horizon_upper(cls, v: int) -> int:
        # Capped to keep the per-trip instance count bounded; 60 days is
        # already a generous booking window for a campus commute app.
        if v > 60:
            raise ValueError("trip_horizon_days must be <= 60")
        return v

    @field_validator("cost_per_seat_cap_paisa")
    @classmethod
    def _cost_upper(cls, v: int) -> int:
        # 100 000 paisa = 1000 BDT; refuse to allow absurd caps.
        if v < 0 or v > 100_000:
            raise ValueError("cost_per_seat_cap_paisa must be 0..100000")
        return v

    @field_validator("emergency_number")
    @classmethod
    def _emergency(cls, v: str) -> str:
        if not re.fullmatch(r"\d{3,6}", v or ""):
            raise ValueError("emergency_number must be 3-6 digits")
        return v

    @field_validator("telegram_webhook_secret")
    @classmethod
    def _webhook_secret(cls, v: str | None) -> str | None:
        # When the operator enables the Telegram webhook, the secret token
        # they register with the Bot API must be at least 32 chars; anything
        # shorter is brute-forceable.
        if v is not None and v != "" and len(v) < 32:
            raise ValueError(
                "telegram_webhook_secret must be at least 32 characters when set"
            )
        return v or None

    @field_validator("supported_langs")
    @classmethod
    def _supported_langs(cls, v: str) -> str:
        langs = [s.strip() for s in v.split(",") if s.strip()]
        if not langs:
            raise ValueError("supported_langs must list at least one code")
        for code in langs:
            if not re.fullmatch(r"[a-z]{2}", code):
                raise ValueError(
                    f"supported_langs entry {code!r} is not a 2-letter code"
                )
        return ",".join(langs)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
