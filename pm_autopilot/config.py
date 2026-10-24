"""Runtime configuration, read from environment variables (and an optional .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is optional; plain env vars still work
    load_dotenv = None

ROOT = Path(__file__).resolve().parent.parent


def _as_bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _as_list(value: str | None) -> list[str]:
    return [item.strip() for item in (value or "").split(",") if item.strip()]


def _as_path(value: str | None, default: Path) -> Path:
    if not value:
        return default
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


@dataclass
class Settings:
    project_name: str = "Riyadh Smart Parking App"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    send_emails: bool = False
    gmail_address: str = ""
    gmail_app_password: str = ""
    sender_name: str = "PM Autopilot"
    report_recipients: list[str] = field(default_factory=list)
    utc_offset: str = "+03:00"  # Riyadh (AST) has no daylight saving
    tasks_csv: Path = ROOT / "data" / "tasks.csv"
    outbox_dir: Path = ROOT / "outbox"

    @property
    def use_gemini(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def smtp_ready(self) -> bool:
        return self.send_emails and bool(self.gmail_address and self.gmail_app_password)

    @property
    def sender_address(self) -> str:
        return self.gmail_address or "pm-autopilot@example.com"

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "Settings":
        if load_dotenv is not None:
            load_dotenv(env_file or ROOT / ".env", override=False)
        env = os.environ.get
        defaults = cls()
        return cls(
            project_name=env("PROJECT_NAME") or defaults.project_name,
            gemini_api_key=(env("GEMINI_API_KEY") or "").strip(),
            gemini_model=env("GEMINI_MODEL") or defaults.gemini_model,
            send_emails=_as_bool(env("SEND_EMAILS")),
            gmail_address=(env("GMAIL_ADDRESS") or "").strip(),
            gmail_app_password=(env("GMAIL_APP_PASSWORD") or "").replace(" ", ""),
            sender_name=env("SENDER_NAME") or defaults.sender_name,
            report_recipients=_as_list(env("REPORT_RECIPIENTS")),
            utc_offset=env("MEETING_UTC_OFFSET") or defaults.utc_offset,
            tasks_csv=_as_path(env("TASKS_CSV"), defaults.tasks_csv),
            outbox_dir=_as_path(env("OUTBOX_DIR"), defaults.outbox_dir),
        )
