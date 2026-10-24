"""Deliver emails: DEMO MODE writes them to outbox/, or send via Gmail SMTP when enabled."""
from __future__ import annotations

import html as html_lib
import logging
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from .config import Settings
from .models import Email
from .outbox_index import write_index

log = logging.getLogger(__name__)

GMAIL_HOST, GMAIL_PORT = "smtp.gmail.com", 465


def html_to_text(html: str) -> str:
    """Rough plain-text alternative for clients that do not render HTML."""
    text = re.sub(r"(?is)<title>.*?</title>|<span style=\"display:none[^\"]*\">.*?</span>", "", html)
    text = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|h\d|li)>", "\n", text)
    text = re.sub(r"(?i)</t[dh]>", "  ", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_lib.unescape(text)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip() + "\n"


def demo_banner(email: Email) -> str:
    to = html_lib.escape(", ".join(email.to) or "(no recipients)")
    files = "".join(f" &middot; attachment: {html_lib.escape(a.filename)}" for a in email.attachments)
    return (
        '<div style="font-family:Consolas,monospace;font-size:12px;background:#fff7ed;color:#9a3412;'
        'border-bottom:1px solid #fed7aa;padding:10px 16px;">'
        f"<strong>DEMO MODE - not sent.</strong> To: {to}<br>Subject: {html_lib.escape(email.subject)}{files}</div>"
    )


class Mailer:
    def __init__(self, settings: Settings):
        self.settings = settings
        if settings.send_emails and not settings.smtp_ready:
            log.warning("SEND_EMAILS=true but GMAIL_ADDRESS / GMAIL_APP_PASSWORD are missing - using DEMO MODE.")

    @property
    def mode(self) -> str:
        return "smtp" if self.settings.smtp_ready else "demo"

    def deliver(self, emails: list[Email]) -> list[str]:
        """Deliver all emails; returns a human-readable result line for each."""
        addressed = []
        for email in emails:
            if email.to:
                addressed.append(email)
            else:
                log.warning("Skipping %r - no recipient email address.", email.subject)
        if not addressed:
            return []
        if self.mode == "demo":
            saved = [str(self.save(e)) for e in addressed]
            write_index(self.settings.outbox_dir, self.settings.project_name)
            return saved
        return self._send_smtp(addressed)

    # ---- demo mode

    def save(self, email: Email) -> Path:
        outbox = self.settings.outbox_dir
        outbox.mkdir(parents=True, exist_ok=True)
        path = outbox / f"{email.kind}__{email.slug}.html"
        page = re.sub(r"(<body[^>]*>)", lambda m: m[1] + demo_banner(email), email.html, count=1)
        path.write_text(page, encoding="utf-8")
        for attachment in email.attachments:
            (outbox / attachment.filename).write_bytes(attachment.content)
        return path

    # ---- real sending

    def build_message(self, email: Email) -> EmailMessage:
        msg = EmailMessage()
        msg["From"] = formataddr((self.settings.sender_name, self.settings.gmail_address))
        msg["To"] = ", ".join(email.to)
        msg["Subject"] = email.subject
        msg.set_content(html_to_text(email.html))
        msg.add_alternative(email.html, subtype="html")
        for attachment in email.attachments:
            maintype, subtype = attachment.mime_type.split("/", 1)
            params = {"method": "REQUEST"} if attachment.mime_type == "text/calendar" else {}
            msg.add_attachment(attachment.content, maintype=maintype, subtype=subtype,
                               filename=attachment.filename, params=params)
        return msg

    def verify_login(self) -> None:
        """Log in to Gmail SMTP without sending anything. Raises smtplib/OSError on failure."""
        with smtplib.SMTP_SSL(GMAIL_HOST, GMAIL_PORT, context=ssl.create_default_context(), timeout=30) as smtp:
            smtp.login(self.settings.gmail_address, self.settings.gmail_app_password)

    def _send_smtp(self, emails: list[Email]) -> list[str]:
        results = []
        with smtplib.SMTP_SSL(GMAIL_HOST, GMAIL_PORT, context=ssl.create_default_context(), timeout=30) as smtp:
            smtp.login(self.settings.gmail_address, self.settings.gmail_app_password)
            for email in emails:
                try:
                    smtp.send_message(self.build_message(email))
                    results.append(f"sent to {', '.join(email.to)}: {email.subject}")
                except smtplib.SMTPException as exc:
                    log.error("Failed to send %r: %s", email.subject, exc)
                    results.append(f"FAILED ({exc}): {email.subject}")
        return results
