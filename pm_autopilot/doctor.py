"""`python main.py check` - verify the setup and tell the user exactly what to fix."""
from __future__ import annotations

import smtplib
import sys
from dataclasses import dataclass

from .config import ROOT, Settings, load_dotenv
from .emails import setup_test_email
from .mailer import Mailer
from .parser import GeminiError, call_gemini
from .tracker import TaskTracker


@dataclass
class Check:
    status: str  # OK / WARN / FAIL
    name: str
    detail: str


def run_checks(settings: Settings, send_test: bool = False) -> list[Check]:
    checks: list[Check] = []
    add = lambda status, name, detail: checks.append(Check(status, name, detail))  # noqa: E731

    version = ".".join(map(str, sys.version_info[:3]))
    add("OK" if sys.version_info >= (3, 10) else "FAIL", "Python", version + ("" if sys.version_info >= (3, 10)
        else " - PM Autopilot needs Python 3.10 or newer"))

    if load_dotenv is None:
        add("WARN", ".env support", "python-dotenv not installed - run: pip install -r requirements.txt")
    elif (ROOT / ".env").exists():
        add("OK", ".env file", "found")
    else:
        add("WARN", ".env file", "not found - using defaults (DEMO MODE, rule-based parser). "
                                 "Copy .env.example to .env to configure.")

    try:
        tasks = TaskTracker(settings.tasks_csv).load()
        no_email = sum(1 for t in tasks if not t.is_done and not t.email)
        add("WARN" if no_email else "OK", "Task tracker",
            f"{len(tasks)} tasks in {settings.tasks_csv.name}"
            + (f" - {no_email} open task(s) have no owner email, so they get no reminders" if no_email else ""))
    except (OSError, ValueError) as exc:
        add("FAIL", "Task tracker", f"cannot read {settings.tasks_csv}: {exc}")

    try:
        settings.outbox_dir.mkdir(parents=True, exist_ok=True)
        probe = settings.outbox_dir / ".write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        add("OK", "Outbox folder", f"writable ({settings.outbox_dir})")
    except OSError as exc:
        add("FAIL", "Outbox folder", f"not writable: {exc}")

    if not settings.use_gemini:
        add("WARN", "Gemini AI", "GEMINI_API_KEY not set - using the rule-based parser "
                                 "(free key: https://aistudio.google.com/apikey)")
    else:
        try:
            call_gemini('Reply with exactly this JSON: {"ok": true}', settings, timeout=30)
            add("OK", "Gemini AI", f"API key works ({settings.gemini_model})")
        except GeminiError as exc:
            add("FAIL", "Gemini AI", f"{exc} - check GEMINI_API_KEY / GEMINI_MODEL. "
                                     "The tool will still work using the rule-based parser.")

    if not settings.send_emails:
        add("OK", "Email delivery", "DEMO MODE - emails are saved to outbox/ (set SEND_EMAILS=true to send)")
    elif not settings.smtp_ready:
        add("FAIL", "Email delivery", "SEND_EMAILS=true but GMAIL_ADDRESS or GMAIL_APP_PASSWORD is empty")
    else:
        mailer = Mailer(settings)
        try:
            mailer.verify_login()
            add("OK", "Gmail login", f"signed in as {settings.gmail_address}")
            if send_test:
                result = mailer.deliver([setup_test_email(settings)])
                add("OK" if result and not result[0].startswith("FAILED") else "FAIL", "Test email",
                    result[0] if result else "not sent")
        except smtplib.SMTPAuthenticationError:
            add("FAIL", "Gmail login", "rejected - use a 16-character App Password "
                                       "(https://myaccount.google.com/apppasswords), not your normal password")
        except (smtplib.SMTPException, OSError) as exc:
            add("FAIL", "Gmail login", f"could not connect to smtp.gmail.com: {exc}")
    return checks
