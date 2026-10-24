"""Plain data classes shared across the app."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime

PRIORITIES = ("High", "Medium", "Low")

_PRIORITY_ALIASES = {
    "high": "High", "h": "High", "p1": "High", "urgent": "High", "critical": "High",
    "medium": "Medium", "med": "Medium", "m": "Medium", "p2": "Medium", "normal": "Medium",
    "low": "Low", "l": "Low", "p3": "Low", "minor": "Low",
}

_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y")


def parse_priority(value: str | None) -> str | None:
    """Return a canonical priority (High/Medium/Low) or None if `value` is not one."""
    if not value:
        return None
    return _PRIORITY_ALIASES.get(value.strip().lower().strip("[]()"))


def parse_date(value: str | None) -> date | None:
    """Parse the handful of date formats people actually type in meeting notes."""
    if not value:
        return None
    text = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


@dataclass
class Attendee:
    name: str
    email: str = ""

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>" if self.email else self.name


@dataclass
class ActionItem:
    task: str
    owner: str
    owner_email: str = ""
    due_date: date | None = None
    priority: str = "Medium"


@dataclass
class Meeting:
    title: str
    source: str
    date: date | None = None
    attendees: list[Attendee] = field(default_factory=list)
    summary: str = ""
    decisions: list[str] = field(default_factory=list)
    action_items: list[ActionItem] = field(default_factory=list)
    parser: str = "rules"  # "rules" or "gemini"


@dataclass
class Attachment:
    filename: str
    content: bytes
    mime_type: str = "application/octet-stream"


@dataclass
class Email:
    to: list[str]
    subject: str
    html: str
    kind: str  # mom / followup / reminder / weekly-report / invite - used for outbox filenames
    attachments: list[Attachment] = field(default_factory=list)

    @property
    def slug(self) -> str:
        base = self.to[0].split("@")[0] if len(self.to) == 1 else re.sub(r"^\[[^\]]*\]\s*", "", self.subject)
        return slugify(base)


def slugify(text: str, max_len: int = 60) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:max_len].rstrip("-") or "item"
