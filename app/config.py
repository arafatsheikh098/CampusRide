"""Application configuration via pydantic-settings.

Settings are read from environment variables and a local `.env` file. The
default SECRET_KEY is a clearly fake placeholder; production refuses to start
with it (see `app.security.assert_safe_secret_key`).
"""
from __future__ import annotations

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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
