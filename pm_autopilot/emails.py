"""HTML email builders. Inline styles + table layout so they render in Gmail/Outlook."""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from html import escape
from typing import TYPE_CHECKING, Iterable

from .config import Settings
from .models import Attachment, Email, Meeting
from .tracker import Task

if TYPE_CHECKING:  # avoid import cycles at runtime
    from .report import StatusReport
    from .scheduler import Invite

NAVY = "#0f2747"
ACCENT = "#0f766e"
MUTED = "#64748b"
BORDER = "#e2e8f0"
FONT = "font-family:Segoe UI,Helvetica,Arial,sans-serif;"

PRIORITY_COLORS = {"High": ("#b91c1c", "#fee2e2"), "Medium": ("#92400e", "#fef3c7"), "Low": ("#166534", "#dcfce7")}
STATUS_COLORS = {
    "Done": ("#166534", "#dcfce7"), "In Progress": ("#1d4ed8", "#dbeafe"),
    "Blocked": ("#b91c1c", "#fee2e2"), "Not Started": ("#475569", "#f1f5f9"),
}
RAG_COLORS = {"Green": "#16a34a", "Amber": "#d97706", "Red": "#dc2626"}


# --------------------------------------------------------------------------- building blocks


def fmt_date(value: date | None) -> str:
    return value.strftime("%a %d %b %Y") if value else "No due date"


def first_name(name: str) -> str:
    return name.split()[0] if name.strip() else "there"


def pill(text: str, colors: tuple[str, str]) -> str:
    fg, bg = colors
    return (f'<span style="display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;'
            f'font-weight:600;color:{fg};background:{bg};white-space:nowrap;">{escape(text)}</span>')


def priority_pill(priority: str) -> str:
    return pill(priority, PRIORITY_COLORS.get(priority, PRIORITY_COLORS["Medium"]))


def status_pill(status: str) -> str:
    return pill(status, STATUS_COLORS.get(status, STATUS_COLORS["Not Started"]))


def heading(text: str) -> str:
    return (f'<h2 style="{FONT}font-size:16px;color:{NAVY};margin:28px 0 10px;padding-bottom:6px;'
            f'border-bottom:2px solid {ACCENT};">{escape(text)}</h2>')


def paragraph(html: str) -> str:
    return f'<p style="{FONT}font-size:14px;line-height:1.6;color:#1e293b;margin:0 0 12px;">{html}</p>'


def bullet_list(items: Iterable[str]) -> str:
    lis = "".join(f'<li style="margin:0 0 6px;">{escape(i)}</li>' for i in items)
    return f'<ul style="{FONT}font-size:14px;line-height:1.5;color:#1e293b;margin:0;padding-left:20px;">{lis}</ul>'


def table(headers: list[str], rows: list[list[str]], empty: str = "Nothing to show.") -> str:
    """Rows contain pre-escaped HTML cells."""
    if not rows:
        return paragraph(f'<em style="color:{MUTED};">{escape(empty)}</em>')
    th = "".join(
        f'<th align="left" style="{FONT}font-size:12px;text-transform:uppercase;letter-spacing:.04em;'
        f'color:{MUTED};padding:8px 10px;border-bottom:1px solid {BORDER};background:#f8fafc;">{escape(h)}</th>'
        for h in headers
    )
    body = "".join(
        "<tr>" + "".join(
            f'<td valign="top" style="{FONT}font-size:13px;color:#1e293b;padding:9px 10px;'
            f'border-bottom:1px solid {BORDER};">{cell}</td>' for cell in row
        ) + "</tr>"
        for row in rows
    )
    return (f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
            f'style="border-collapse:collapse;border:1px solid {BORDER};border-radius:6px;">'
            f"<thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>")


def stat_tiles(stats: list[tuple[str, str, str]]) -> str:
    """stats: (label, value, color)."""
    cells = "".join(
        f'<td align="center" style="padding:14px 6px;border:1px solid {BORDER};border-radius:6px;background:#ffffff;">'
        f'<div style="{FONT}font-size:26px;font-weight:700;color:{color};">{escape(value)}</div>'
        f'<div style="{FONT}font-size:12px;color:{MUTED};margin-top:2px;">{escape(label)}</div></td>'
        for label, value, color in stats
    )
    return (f'<table role="presentation" width="100%" cellspacing="6" cellpadding="0" '
            f'style="border-collapse:separate;"><tr>{cells}</tr></table>')


def callout(html: str, color: str = ACCENT) -> str:
    return (f'<div style="{FONT}font-size:14px;line-height:1.5;color:#1e293b;background:#f8fafc;'
            f'border-left:4px solid {color};padding:12px 14px;margin:0 0 16px;">{html}</div>')


def layout(settings: Settings, label: str, title: str, body: str, preheader: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{escape(title)}</title></head>
<body style="margin:0;padding:0;background:#eef2f7;">
<span style="display:none;max-height:0;overflow:hidden;">{escape(preheader)}</span>
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#eef2f7;padding:24px 12px;">
<tr><td align="center">
<table role="presentation" width="640" cellspacing="0" cellpadding="0" style="max-width:640px;width:100%;background:#ffffff;border-radius:10px;overflow:hidden;box-shadow:0 1px 3px rgba(15,39,71,.12);">
<tr><td style="background:{NAVY};padding:22px 28px;">
<div style="{FONT}font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#7dd3c8;">{escape(label)}</div>
<div style="{FONT}font-size:21px;font-weight:700;color:#ffffff;margin-top:4px;">{escape(title)}</div>
<div style="{FONT}font-size:13px;color:#cbd5e1;margin-top:4px;">{escape(settings.project_name)}</div>
</td></tr>
<tr><td style="padding:8px 28px 28px;">{body}</td></tr>
<tr><td style="background:#f8fafc;border-top:1px solid {BORDER};padding:14px 28px;{FONT}font-size:12px;color:{MUTED};">
Sent by {escape(settings.sender_name)} &middot; automated project communication for {escape(settings.project_name)}.
Reply to this email if anything looks wrong.
</td></tr>
</table></td></tr></table></body></html>"""


def task_rows(tasks: Iterable[Task], today: date | None = None, show_owner: bool = True) -> list[list[str]]:
    rows = []
    for t in tasks:
        due = f'<span style="white-space:nowrap;">{escape(t.due_date.strftime("%d %b %Y") if t.due_date else "-")}</span>'
        if today and t.due_date:
            days = t.days_until_due(today)
            if days < 0:
                due += f'<br><span style="color:#b91c1c;font-weight:600;">{-days} day{"s" if days != -1 else ""} overdue</span>'
            elif days <= 2:
                due += f'<br><span style="color:#d97706;font-weight:600;">{"due today" if days == 0 else f"due in {days} day" + ("s" if days > 1 else "")}</span>'
        row = [f'<span style="color:{MUTED};white-space:nowrap;">{escape(t.id)}</span>', escape(t.task)]
        if show_owner:
            row.append(escape(t.owner))
        row += [due, priority_pill(t.priority), status_pill(t.status)]
        rows.append(row)
    return rows


def task_headers(show_owner: bool = True) -> list[str]:
    return ["ID", "Task"] + (["Owner"] if show_owner else []) + ["Due", "Priority", "Status"]


# --------------------------------------------------------------------------- emails


def mom_email(meeting: Meeting, tasks: list[Task], settings: Settings) -> Email:
    when = fmt_date(meeting.date) if meeting.date else "Date not recorded"
    attendees = ", ".join(escape(a.name) for a in meeting.attendees) or "Not recorded"
    body = (
        paragraph("Hello team,")
        + paragraph(f"Please find below the minutes of <strong>{escape(meeting.title)}</strong> held on "
                    f"<strong>{escape(when)}</strong>. Owners will also receive a separate follow-up with their tasks.")
        + callout(f"<strong>Attendees:</strong> {attendees}")
        + heading("Summary") + paragraph(escape(meeting.summary or "No summary recorded."))
        + heading(f"Decisions ({len(meeting.decisions)})")
        + (bullet_list(meeting.decisions) if meeting.decisions else paragraph(f'<em style="color:{MUTED};">No decisions recorded.</em>'))
        + heading(f"Action items ({len(tasks)})")
        + table(task_headers(), task_rows(tasks), empty="No action items recorded.")
        + paragraph("<br>Please reply within 24 hours if anything is missing or inaccurate.<br><br>Best regards,<br>"
                    f"{escape(settings.sender_name)}")
    )
    recipients = [a.email for a in meeting.attendees if a.email]
    return Email(
        to=recipients,
        subject=f"[MoM] {meeting.title} - {meeting.date.isoformat() if meeting.date else 'notes'}",
        html=layout(settings, "Minutes of Meeting", meeting.title, body,
                    preheader=f"{len(meeting.decisions)} decisions, {len(tasks)} action items"),
        kind="mom",
    )


def followup_emails(meeting: Meeting, tasks: list[Task], settings: Settings) -> list[Email]:
    by_owner: dict[str, list[Task]] = defaultdict(list)
    for task in tasks:
        if task.email:
            by_owner[task.email].append(task)
    emails = []
    for address, owned in by_owner.items():
        name = owned[0].owner
        body = (
            paragraph(f"Hi {escape(first_name(name))},")
            + paragraph(f"Thanks for joining <strong>{escape(meeting.title)}</strong>. "
                        f"You own <strong>{len(owned)}</strong> action item{'s' if len(owned) != 1 else ''} from the meeting:")
            + table(task_headers(show_owner=False), task_rows(owned, show_owner=False))
            + paragraph("<br>If a due date is not realistic or you are blocked, reply to this email so we can "
                        "re-plan early rather than late.<br><br>Thanks,<br>" + escape(settings.sender_name))
        )
        emails.append(Email(
            to=[address],
            subject=f"[Action required] Your {len(owned)} task{'s' if len(owned) != 1 else ''} from {meeting.title}",
            html=layout(settings, "Follow-up", f"Your action items, {first_name(name)}", body,
                        preheader=f"{len(owned)} task(s) from {meeting.title}"),
            kind="followup",
        ))
    return emails


def reminder_email(owner: str, address: str, tasks: list[Task], today: date, settings: Settings) -> Email:
    overdue = [t for t in tasks if t.is_overdue(today)]
    due_soon = [t for t in tasks if not t.is_overdue(today)]
    intro = []
    if overdue:
        intro.append(f'<strong style="color:#b91c1c;">{len(overdue)} overdue</strong>')
    if due_soon:
        intro.append(f'<strong style="color:#d97706;">{len(due_soon)} due in the next 2 days</strong>')
    body = (
        paragraph(f"Hi {escape(first_name(owner))},")
        + paragraph(f"Friendly reminder: you have {' and '.join(intro)}.")
        + table(task_headers(show_owner=False), task_rows(sorted(tasks, key=lambda t: t.due_date), today, show_owner=False))
        + paragraph("<br>Could you update the status, or let me know a new realistic date and anything blocking you?"
                    "<br><br>Thanks,<br>" + escape(settings.sender_name))
    )
    subject = (f"[Overdue] {len(overdue)} task{'s need' if len(overdue) != 1 else ' needs'} attention" if overdue
               else f"[Reminder] {len(due_soon)} task{'s' if len(due_soon) != 1 else ''} due soon")
    return Email(
        to=[address], subject=f"{subject} - {settings.project_name}",
        html=layout(settings, "Task reminder", f"Reminder for {owner}", body,
                    preheader=f"{len(overdue)} overdue, {len(due_soon)} due soon"),
        kind="reminder",
    )


def weekly_report_email(report: "StatusReport", recipients: list[str], settings: Settings) -> Email:
    rag_color = RAG_COLORS[report.rag]
    owner_rows = [
        [escape(o.owner), str(o.open), str(o.done),
         f'<span style="color:{"#b91c1c" if o.overdue else "#1e293b"};font-weight:{700 if o.overdue else 400};">{o.overdue}</span>']
        for o in report.by_owner
    ]
    body = (
        paragraph("Hello all,")
        + paragraph(f"Here is the weekly status for <strong>{escape(settings.project_name)}</strong> "
                    f"for the week of <strong>{escape(fmt_date(report.week_start))}</strong>.")
        + callout(
            f'<span style="display:inline-block;padding:3px 12px;border-radius:999px;background:{rag_color};'
            f'color:#fff;font-weight:700;font-size:13px;margin-right:8px;">{report.rag.upper()}</span>'
            f"<strong>Overall status.</strong> {escape(report.rag_reason)}", rag_color)
        + stat_tiles([
            ("Total", str(report.total), NAVY),
            ("Done", str(report.done), "#16a34a"),
            ("In progress", str(report.in_progress), "#1d4ed8"),
            ("Overdue", str(len(report.overdue)), "#dc2626"),
        ])
        + paragraph(f'<span style="color:{MUTED};font-size:13px;">Completion {report.completion_pct}% &middot; '
                    f"{report.not_started} not started &middot; {report.blocked} blocked</span>")
        + heading(f"Overdue tasks ({len(report.overdue)})")
        + table(task_headers(), task_rows(report.overdue, report.today), empty="No overdue tasks - great work!")
        + heading(f"Due in the next 7 days ({len(report.due_next_week)})")
        + table(task_headers(), task_rows(report.due_next_week, report.today), empty="Nothing due next week.")
        + heading("Workload by owner")
        + table(["Owner", "Open", "Done", "Overdue"], owner_rows)
        + paragraph("<br>Regards,<br>" + escape(settings.sender_name))
    )
    return Email(
        to=recipients,
        subject=f"[Weekly Status: {report.rag}] {settings.project_name} - week of {report.week_start.isoformat()}",
        html=layout(settings, "Weekly status report", f"Week of {fmt_date(report.week_start)}", body,
                    preheader=f"{report.rag}: {report.done}/{report.total} done, {len(report.overdue)} overdue"),
        kind="weekly-report",
    )


def setup_test_email(settings: Settings) -> Email:
    body = (
        paragraph("Hi,")
        + paragraph("This is a test from <strong>PM Autopilot</strong>. If you can read it, Gmail sending works "
                    "and real emails (minutes, follow-ups, reminders, reports, invites) will be delivered.")
        + callout("Tip: send everything to yourself first by keeping your own address as the only attendee "
                  "in a sample meeting file.")
    )
    return Email(to=[settings.gmail_address], subject=f"[Test] PM Autopilot is set up - {settings.project_name}",
                 html=layout(settings, "Setup check", "Email delivery works", body), kind="test")


def invite_email(invite: "Invite", ics_text: str, settings: Settings) -> Email:
    end = invite.end
    agenda = bullet_list(invite.agenda) if invite.agenda else paragraph(f'<em style="color:{MUTED};">Agenda to follow.</em>')
    body = (
        paragraph("Hello,")
        + paragraph(f"You are invited to <strong>{escape(invite.title)}</strong>. The calendar invite is attached "
                    "(.ics) - open it to add the meeting to Outlook, Google Calendar or Apple Calendar.")
        + callout(
            f"<strong>When:</strong> {escape(invite.start.strftime('%A %d %B %Y, %H:%M'))} - {escape(end.strftime('%H:%M'))} "
            f"(UTC{escape(invite.utc_offset)})<br><strong>Where:</strong> {escape(invite.location)}<br>"
            f"<strong>Attendees:</strong> {escape(', '.join(invite.attendees))}")
        + heading("Agenda") + agenda
        + paragraph("<br>Please accept or propose a new time from your calendar.<br><br>Best regards,<br>"
                    + escape(settings.sender_name))
    )
    return Email(
        to=invite.attendees,
        subject=f"[Invite] {invite.title} - {invite.start.strftime('%a %d %b %Y %H:%M')}",
        html=layout(settings, "Meeting invitation", invite.title, body,
                    preheader=invite.start.strftime("%A %d %B, %H:%M")),
        kind="invite",
        attachments=[Attachment(f"{invite.slug}.ics", ics_text.encode("utf-8"), "text/calendar")],
    )
