"""Create RFC 5545 (.ics) calendar invites that Outlook, Google Calendar and Apple Calendar accept."""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .models import slugify


def parse_utc_offset(offset: str) -> timezone:
    match = re.fullmatch(r"([+-])(\d{1,2}):?(\d{2})?", offset.strip())
    if not match:
        raise ValueError(f"Invalid UTC offset {offset!r} - expected e.g. +03:00")
    sign = -1 if match[1] == "-" else 1
    return timezone(sign * timedelta(hours=int(match[2]), minutes=int(match[3] or 0)))


@dataclass
class Invite:
    title: str
    start: datetime  # local wall-clock time (naive), interpreted with utc_offset
    attendees: list[str]
    duration_minutes: int = 60
    agenda: list[str] = field(default_factory=list)
    location: str = "Microsoft Teams"
    organizer_name: str = "PM Autopilot"
    organizer_email: str = "pm-autopilot@example.com"
    utc_offset: str = "+03:00"
    uid: str = field(default_factory=lambda: f"{uuid.uuid4()}@pm-autopilot")

    @property
    def end(self) -> datetime:
        return self.start + timedelta(minutes=self.duration_minutes)

    @property
    def slug(self) -> str:
        return f"{slugify(self.title)}-{self.start:%Y%m%d-%H%M}"

    def to_utc(self, moment: datetime) -> datetime:
        return moment.replace(tzinfo=parse_utc_offset(self.utc_offset)).astimezone(timezone.utc)


def escape_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")


def fold(line: str) -> str:
    """Fold content lines at 75 octets (RFC 5545 section 3.1) without splitting UTF-8 characters."""
    out, current, size = [], "", 0
    for char in line:
        width = len(char.encode("utf-8"))
        limit = 75 if not out else 74  # continuation lines start with a space
        if size + width > limit:
            out.append(current)
            current, size = "", 0
        current += char
        size += width
    out.append(current)
    return "\r\n ".join(out)


def _utc(moment: datetime) -> str:
    return moment.strftime("%Y%m%dT%H%M%SZ")


def build_ics(invite: Invite, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    description = "Agenda:\n" + "\n".join(f"{i}. {item}" for i, item in enumerate(invite.agenda, 1)) if invite.agenda else ""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//PM Autopilot//Meeting Scheduler//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:REQUEST",
        "BEGIN:VEVENT",
        f"UID:{invite.uid}",
        f"DTSTAMP:{_utc(now)}",
        f"DTSTART:{_utc(invite.to_utc(invite.start))}",
        f"DTEND:{_utc(invite.to_utc(invite.end))}",
        f"SUMMARY:{escape_text(invite.title)}",
        f"DESCRIPTION:{escape_text(description)}",
        f"LOCATION:{escape_text(invite.location)}",
        f"ORGANIZER;CN={escape_text(invite.organizer_name)}:mailto:{invite.organizer_email}",
        *(f"ATTENDEE;CUTYPE=INDIVIDUAL;ROLE=REQ-PARTICIPANT;PARTSTAT=NEEDS-ACTION;RSVP=TRUE:mailto:{a}"
          for a in invite.attendees),
        "SEQUENCE:0",
        "STATUS:CONFIRMED",
        "TRANSP:OPAQUE",
        "BEGIN:VALARM",
        "ACTION:DISPLAY",
        "DESCRIPTION:Reminder",
        "TRIGGER:-PT15M",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
    ]
    return "\r\n".join(fold(line) for line in lines) + "\r\n"
