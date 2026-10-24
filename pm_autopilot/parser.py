"""Turn raw meeting notes into a structured Meeting.

Two strategies:
  * Gemini (if GEMINI_API_KEY is set) - understands free-form notes.
  * Rule-based fallback - reads tagged lines such as
        ACTION: Ali - finish API docs - 2026-11-05 - High
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from pathlib import Path

from .config import Settings
from .models import ActionItem, Attendee, Meeting, parse_date, parse_priority

log = logging.getLogger(__name__)

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

_TAG_RE = re.compile(r"^\s*(?:[-*•]\s*)?(TITLE|DATE|ATTENDEES|SUMMARY|DECISION|ACTION)\s*:\s*(.*)$", re.I)
_FIELD_SPLIT_RE = re.compile(r"\s+[-–—|]\s+")
_ATTENDEE_RE = re.compile(r"^(?P<name>[^<(]*?)\s*[<(]\s*(?P<email>[^>)\s]+@[^>)\s]+)\s*[>)]$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class GeminiError(RuntimeError):
    pass


# --------------------------------------------------------------------------- rule-based


def parse_attendees(text: str) -> list[Attendee]:
    attendees = []
    for chunk in re.split(r"[,;]", text):
        chunk = chunk.strip()
        if not chunk:
            continue
        match = _ATTENDEE_RE.match(chunk)
        if match:
            attendees.append(Attendee(match["name"].strip() or match["email"], match["email"]))
        elif _EMAIL_RE.match(chunk):
            attendees.append(Attendee(chunk.split("@")[0], chunk))
        else:
            attendees.append(Attendee(chunk))
    return attendees


def resolve_email(owner: str, attendees: list[Attendee]) -> str:
    """Find an owner's email from the attendee list by full name, then first name."""
    owner_key = owner.strip().lower()
    if _EMAIL_RE.match(owner_key):
        return owner_key
    for attendee in attendees:
        if attendee.email and attendee.name.lower() == owner_key:
            return attendee.email
    for attendee in attendees:
        if attendee.email and attendee.name.lower().split()[:1] == owner_key.split()[:1]:
            return attendee.email
    return ""


def resolve_owner_name(owner: str, attendees: list[Attendee]) -> str:
    """Expand a first name ("Ali") to the attendee's full name ("Ali Hassan") when unambiguous."""
    matches = [a for a in attendees if a.name.lower().split()[:1] == owner.lower().split()[:1]]
    return matches[0].name if len(matches) == 1 and len(owner.split()) == 1 else owner


def parse_action_line(text: str, attendees: list[Attendee]) -> ActionItem | None:
    """Parse "Owner - task - due date [- priority]". Date and priority may come in any order at the end."""
    parts = [p.strip() for p in _FIELD_SPLIT_RE.split(text.strip()) if p.strip()]
    if len(parts) < 2:
        log.warning("Skipping action line without 'Owner - task': %r", text)
        return None
    owner, rest = parts[0], parts[1:]
    due_date, priority = None, None
    while len(rest) > 1:
        if due_date is None and parse_date(rest[-1]):
            due_date = parse_date(rest.pop())
        elif priority is None and parse_priority(rest[-1]):
            priority = parse_priority(rest.pop())
        else:
            break
    task = " - ".join(rest)
    return ActionItem(
        task=task[:1].upper() + task[1:],
        owner=resolve_owner_name(owner, attendees),
        owner_email=resolve_email(owner, attendees),
        due_date=due_date,
        priority=priority or "Medium",
    )


def parse_rules(text: str, source: str) -> Meeting:
    meeting = Meeting(title="", source=source, parser="rules")
    summary_parts: list[str] = []
    untagged: list[str] = []
    action_lines: list[str] = []

    for raw in text.splitlines():
        if raw.lstrip().startswith("#"):  # comment lines, e.g. in templates/meeting_notes_template.txt
            continue
        match = _TAG_RE.match(raw)
        if not match:
            line = raw.strip().lstrip("-*• ").strip()
            if line and not line.isupper():  # skip blank lines and section headings like "DISCUSSION"
                untagged.append(line)
            continue
        tag, value = match[1].upper(), match[2].strip()
        if tag == "TITLE":
            meeting.title = value
        elif tag == "DATE":
            meeting.date = parse_date(value)
        elif tag == "ATTENDEES":
            meeting.attendees.extend(parse_attendees(value))
        elif tag == "SUMMARY":
            summary_parts.append(value)
        elif tag == "DECISION" and value:
            meeting.decisions.append(value)
        elif tag == "ACTION":
            action_lines.append(value)  # parsed after attendees are known

    for line in action_lines:
        item = parse_action_line(line, meeting.attendees)
        if item:
            meeting.action_items.append(item)

    meeting.title = meeting.title or Path(source).stem.replace("_", " ").title()
    meeting.summary = " ".join(summary_parts) or " ".join(untagged[:3])
    return meeting


# --------------------------------------------------------------------------- Gemini

_PROMPT = """You are a meticulous project management assistant.
Extract structured information from the meeting notes below and reply with JSON only, matching:
{{
  "title": string,
  "date": "YYYY-MM-DD" or null,
  "attendees": [{{"name": string, "email": string or ""}}],
  "summary": string (3-5 sentences, executive tone),
  "decisions": [string],
  "action_items": [{{"task": string, "owner": string, "owner_email": string or "",
                    "due_date": "YYYY-MM-DD" or null, "priority": "High" | "Medium" | "Low"}}]
}}
Rules:
- Use attendees' full names for owners and copy their emails from the attendee list when known.
- Resolve relative due dates ("next Friday") against the meeting date ({meeting_date}).
- Default priority to "Medium" when it is not stated or implied.
- Do not invent action items that are not in the notes.

MEETING NOTES:
\"\"\"
{notes}
\"\"\"
"""


def call_gemini(prompt: str, settings: Settings, timeout: int = 60) -> dict:
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
    }
    request = urllib.request.Request(
        GEMINI_URL.format(model=settings.gemini_model),
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": settings.gemini_api_key},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        text = payload["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(text)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise GeminiError(f"Gemini HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, KeyError, IndexError, json.JSONDecodeError) as exc:
        raise GeminiError(f"Gemini request failed: {exc}") from exc


def meeting_from_gemini(data: dict, fallback: Meeting) -> Meeting:
    """Build a Meeting from Gemini's JSON, filling gaps from the rule-based parse."""
    attendees = [
        Attendee(str(a.get("name") or "").strip(), str(a.get("email") or "").strip())
        for a in data.get("attendees") or []
        if isinstance(a, dict) and (a.get("name") or a.get("email"))
    ] or fallback.attendees
    # Emails written in the notes are more trustworthy than the model's guesses.
    known = {a.name.lower(): a.email for a in fallback.attendees if a.email}
    for attendee in attendees:
        attendee.email = known.get(attendee.name.lower(), attendee.email)

    items = []
    for raw in data.get("action_items") or []:
        if not isinstance(raw, dict) or not str(raw.get("task") or "").strip():
            continue
        owner = str(raw.get("owner") or "Unassigned").strip()
        items.append(ActionItem(
            task=str(raw["task"]).strip(),
            owner=owner,
            owner_email=resolve_email(owner, attendees) or str(raw.get("owner_email") or "").strip(),
            due_date=parse_date(str(raw.get("due_date") or "")),
            priority=parse_priority(str(raw.get("priority") or "")) or "Medium",
        ))

    return Meeting(
        title=str(data.get("title") or "").strip() or fallback.title,
        source=fallback.source,
        date=parse_date(str(data.get("date") or "")) or fallback.date,
        attendees=attendees,
        summary=str(data.get("summary") or "").strip() or fallback.summary,
        decisions=[str(d).strip() for d in data.get("decisions") or [] if str(d).strip()] or fallback.decisions,
        action_items=items or fallback.action_items,
        parser="gemini",
    )


# --------------------------------------------------------------------------- entry point


def parse_meeting(path: Path, settings: Settings) -> Meeting:
    text = Path(path).read_text(encoding="utf-8")
    rules = parse_rules(text, Path(path).name)
    if not settings.use_gemini:
        return rules
    try:
        prompt = _PROMPT.format(meeting_date=rules.date or "unknown", notes=text)
        return meeting_from_gemini(call_gemini(prompt, settings), rules)
    except GeminiError as exc:
        log.warning("%s - falling back to the rule-based parser.", exc)
        return rules
