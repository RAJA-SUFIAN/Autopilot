"""PM Autopilot command-line interface.

    python main.py process meetings/sprint_review.txt
    python main.py reminders
    python main.py weekly-report
    python main.py schedule --title "Sprint Planning" --date 2026-11-02 --time 10:00 --attendees a@x.com,b@x.com
    python main.py tasks
    python main.py add "Book launch venue" --owner "Sara" --email sara@x.com --due 2026-11-20
    python main.py update T-012 --status done
    python main.py check
    python main.py serve
    python main.py demo
"""
from __future__ import annotations

import argparse
import logging
import re
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

from pm_autopilot.config import ROOT, Settings
from pm_autopilot.doctor import run_checks
from pm_autopilot.emails import followup_emails, invite_email, mom_email, weekly_report_email
from pm_autopilot.mailer import Mailer
from pm_autopilot.models import ActionItem, parse_priority
from pm_autopilot.outbox_index import write_index
from pm_autopilot.parser import parse_meeting
from pm_autopilot.reminders import build_reminders
from pm_autopilot.report import build_report
from pm_autopilot.scheduler import Invite, build_ics
from pm_autopilot.server import serve
from pm_autopilot.tracker import STATUSES, TaskTracker, normalize_status

EMAIL_RE = re.compile(r"^[^@\s,]+@[^@\s,]+\.[^@\s,]+$")


def rel(path: Path | str) -> str:
    try:
        return str(Path(path).resolve().relative_to(Path.cwd()))
    except ValueError:
        return str(path)


def deliver(mailer: Mailer, emails: list) -> None:
    target = f"DEMO MODE -> {rel(mailer.settings.outbox_dir)}/" if mailer.mode == "demo" else "Gmail SMTP"
    results = mailer.deliver(emails)
    print(f"Emails ({len(results)}, {target}):")
    for line in results:
        print(f"  {rel(line) if mailer.mode == 'demo' else line}")
    if results and mailer.mode == "demo":
        print(f"  Browse them all: {rel(mailer.settings.outbox_dir / 'index.html')}")


# --------------------------------------------------------------------------- commands


def cmd_process(args, settings: Settings) -> int:
    path = Path(args.file)
    if not path.exists():
        print(f"error: meeting notes not found: {path}", file=sys.stderr)
        return 1
    meeting = parse_meeting(path, settings)
    print(f"Processed {rel(path)} (parser: {meeting.parser})")
    print(f"  Title:        {meeting.title}")
    print(f"  Date:         {meeting.date or 'unknown'}")
    print(f"  Attendees:    {len(meeting.attendees)}")
    print(f"  Decisions:    {len(meeting.decisions)}")
    print(f"  Action items: {len(meeting.action_items)}")

    tracker = TaskTracker(settings.tasks_csv)
    meeting_tasks, added = tracker.add_action_items(meeting.action_items, path.name)
    print(f"Tracker: {len(added)} added, {len(meeting_tasks) - len(added)} already tracked "
          f"-> {rel(settings.tasks_csv)}")
    for task in added:
        print(f"  + {task.id}  {task.owner:<18} {task.task}  (due {task.due_date or '-'}, {task.priority})")

    if args.no_emails:
        return 0
    emails = [mom_email(meeting, meeting_tasks, settings), *followup_emails(meeting, meeting_tasks, settings)]
    deliver(Mailer(settings), emails)
    return 0


def cmd_reminders(args, settings: Settings) -> int:
    tasks = TaskTracker(settings.tasks_csv).load()
    emails = build_reminders(tasks, args.today, settings, window_days=args.window)
    print(f"Reminders for {args.today} (overdue or due within {args.window} days): {len(emails)} owner(s)")
    if emails:
        deliver(Mailer(settings), emails)
    return 0


def cmd_weekly_report(args, settings: Settings) -> int:
    tasks = TaskTracker(settings.tasks_csv).load()
    report = build_report(tasks, args.today)
    recipients = settings.report_recipients or sorted({t.email for t in tasks if t.email})
    print(f"Weekly status for week of {report.week_start}: {report.rag}")
    print(f"  {report.rag_reason}")
    print(f"  Total {report.total} | Done {report.done} | In progress {report.in_progress} | "
          f"Overdue {len(report.overdue)} | Blocked {report.blocked} | Not started {report.not_started}")
    deliver(Mailer(settings), [weekly_report_email(report, recipients, settings)])
    return 0


def cmd_schedule(args, settings: Settings) -> int:
    try:
        start = datetime.strptime(f"{args.date} {args.time}", "%Y-%m-%d %H:%M")
    except ValueError:
        print("error: use --date YYYY-MM-DD and --time HH:MM (24h)", file=sys.stderr)
        return 1
    attendees = [a.strip() for a in args.attendees.split(",") if a.strip()]
    invalid = [a for a in attendees if not EMAIL_RE.match(a)]
    if invalid or not attendees:
        print(f"error: invalid attendee email(s): {', '.join(invalid) or '(none given)'}", file=sys.stderr)
        return 1
    invite = Invite(
        title=args.title, start=start, attendees=attendees, duration_minutes=args.duration,
        agenda=[a.strip() for a in (args.agenda or "").split(";") if a.strip()],
        location=args.location, organizer_name=settings.sender_name,
        organizer_email=settings.sender_address, utc_offset=settings.utc_offset,
    )
    ics = build_ics(invite)
    print(f"Scheduled '{invite.title}' on {start:%a %d %b %Y %H:%M} (UTC{invite.utc_offset}), "
          f"{invite.duration_minutes} min, {len(attendees)} attendee(s)")
    mailer = Mailer(settings)
    deliver(mailer, [invite_email(invite, ics, settings)])
    if mailer.mode == "demo":
        print(f"  {rel(settings.outbox_dir / (invite.slug + '.ics'))}  <- open to add to your calendar")
    return 0


def cmd_tasks(args, settings: Settings) -> int:
    tasks = TaskTracker(settings.tasks_csv).load()
    if args.open:
        tasks = [t for t in tasks if not t.is_done]
    print(f"{'ID':<6} {'Status':<12} {'Pri':<7} {'Due':<11} {'Owner':<18} Task")
    for t in tasks:
        flag = " (OVERDUE)" if t.is_overdue(args.today) else ""
        print(f"{t.id:<6} {t.status:<12} {t.priority:<7} {str(t.due_date or '-'):<11} {t.owner:<18} {t.task}{flag}")
    print(f"\n{len(tasks)} task(s) in {rel(settings.tasks_csv)}")
    return 0


def cmd_add(args, settings: Settings) -> int:
    priority = parse_priority(args.priority)
    if priority is None:
        print(f"error: --priority must be High, Medium or Low (got {args.priority!r})", file=sys.stderr)
        return 1
    if args.email and not EMAIL_RE.match(args.email):
        print(f"error: invalid --email {args.email!r}", file=sys.stderr)
        return 1
    tracker = TaskTracker(settings.tasks_csv)
    owner, email = tracker.known_owner(args.owner.strip(), args.email or "")
    item = ActionItem(args.task.strip(), owner, email, args.due, priority)
    matched, added = tracker.add_action_items([item], "manual")
    if not added:
        print(f"Already tracked as {matched[0].id}: {matched[0].owner} - {matched[0].task}")
        return 0
    task = added[0]
    print(f"Added {task.id}: {task.task} ({task.owner}, due {task.due_date or '-'}, {task.priority})")
    if not task.email:
        print("  note: no --email given, so this owner will not get reminder emails")
    return 0


def cmd_update(args, settings: Settings) -> int:
    status = None
    if args.status:
        status = normalize_status(args.status)
        if status is None:
            print(f"error: --status must be one of: {', '.join(STATUSES)}", file=sys.stderr)
            return 1
    priority = parse_priority(args.priority) if args.priority else None
    if args.priority and priority is None:
        print("error: --priority must be High, Medium or Low", file=sys.stderr)
        return 1
    changes = dict(status=status, priority=priority, due_date=args.due, owner=args.owner, email=args.email)
    if all(v is None for v in changes.values()):
        print("error: nothing to change - pass --status, --due, --priority, --owner or --email", file=sys.stderr)
        return 1
    updated, missing = TaskTracker(settings.tasks_csv).update(args.ids, **changes)
    for task in updated:
        print(f"Updated {task.id}: {task.task}  -> {task.status}, due {task.due_date or '-'}, {task.priority}")
    for task_id in missing:
        print(f"error: no task with ID {task_id} (see: python main.py tasks)", file=sys.stderr)
    return 1 if missing else 0


def cmd_reset(args, settings: Settings) -> int:
    path = settings.tasks_csv
    count = len(TaskTracker(path).load())
    if not args.yes:
        print(f"This empties {rel(path)} ({count} tasks) so you can start your own project.")
        print("A backup copy is kept next to it. Re-run with --yes to confirm.")
        return 1
    if path.exists():
        backup = path.with_name(f"{path.stem}.backup-{datetime.now():%Y%m%d-%H%M%S}{path.suffix}")
        shutil.copy2(path, backup)
        print(f"Backed up {count} tasks to {rel(backup)}")
    TaskTracker(path).save([])
    print(f"{rel(path)} is now empty. Next: python main.py process meetings/<your notes>.txt")
    return 0


def cmd_check(args, settings: Settings) -> int:
    print("PM Autopilot setup check\n")
    checks = run_checks(settings, send_test=args.send_test)
    for check in checks:
        print(f"  [{check.status:<4}] {check.name:<15} {check.detail}")
    failed = sum(c.status == "FAIL" for c in checks)
    print("\n" + ("All good - you're ready to go." if not failed else f"{failed} problem(s) to fix above."))
    return 1 if failed else 0


def cmd_serve(args, settings: Settings) -> int:
    if not (settings.outbox_dir / "index.html").exists():
        settings.outbox_dir.mkdir(parents=True, exist_ok=True)
        write_index(settings.outbox_dir, settings.project_name)
    serve(settings.outbox_dir, port=args.port, open_browser=not args.no_browser)
    return 0


def cmd_demo(args, settings: Settings) -> int:
    steps = [
        ("process", lambda: cmd_process(argparse.Namespace(file=str(ROOT / "meetings" / "sprint_review.txt"),
                                                           no_emails=False, today=args.today), settings)),
        ("reminders", lambda: cmd_reminders(argparse.Namespace(today=args.today, window=2), settings)),
        ("weekly-report", lambda: cmd_weekly_report(args, settings)),
        ("schedule", lambda: cmd_schedule(argparse.Namespace(
            title="Sprint 4 Planning", date="2026-11-02", time="10:00", duration=90, location="KAFD Office, Room 3B",
            attendees="sara.alqahtani@example.com,ali.hassan@example.com,noura.alharbi@example.com,"
                      "omar.farooq@example.com,lina.haddad@example.com,khalid.almutairi@example.com",
            agenda="Sprint 3 retro highlights; Review pilot launch blockers; Capacity and sprint goal; Commit sprint backlog",
        ), settings)),
    ]
    for name, run in steps:
        print(f"\n=== {name} " + "=" * (60 - len(name)))
        if run() != 0:
            return 1
    return 0


# --------------------------------------------------------------------------- argparse


def iso_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"expected YYYY-MM-DD, got {value!r}") from exc


def build_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--today", type=iso_date, default=date.today(),
                        help="pretend today is YYYY-MM-DD (reproducible demos)")

    parser = argparse.ArgumentParser(prog="pm-autopilot", description="Project management automation.")
    sub = parser.add_subparsers(dest="command", metavar="<command>")

    p = sub.add_parser("process", parents=[common], help="extract MoM + action items from meeting notes")
    p.add_argument("file", help="path to a .txt meeting notes file, e.g. meetings/sprint_review.txt")
    p.add_argument("--no-emails", action="store_true", help="only update the task tracker")
    p.set_defaults(func=cmd_process)

    p = sub.add_parser("reminders", parents=[common], help="remind owners of overdue / soon-due tasks")
    p.add_argument("--window", type=int, default=2, help="days ahead to include (default 2)")
    p.set_defaults(func=cmd_reminders)

    p = sub.add_parser("weekly-report", parents=[common], help="weekly status report with RAG rating")
    p.set_defaults(func=cmd_weekly_report)

    p = sub.add_parser("schedule", parents=[common], help="create a .ics meeting invite")
    p.add_argument("--title", required=True)
    p.add_argument("--date", required=True, help="YYYY-MM-DD")
    p.add_argument("--time", required=True, help="HH:MM, 24h local time")
    p.add_argument("--attendees", required=True, help="comma-separated emails")
    p.add_argument("--duration", type=int, default=60, help="minutes (default 60)")
    p.add_argument("--agenda", help='semicolon-separated items, e.g. "Retro; Backlog; Sprint goal"')
    p.add_argument("--location", default="Microsoft Teams")
    p.set_defaults(func=cmd_schedule)

    p = sub.add_parser("tasks", parents=[common], help="list tracked tasks")
    p.add_argument("--open", action="store_true", help="hide completed tasks")
    p.set_defaults(func=cmd_tasks)

    p = sub.add_parser("add", parents=[common], help="add a task by hand")
    p.add_argument("task", help='task description, e.g. "Book venue for launch event"')
    p.add_argument("--owner", required=True)
    p.add_argument("--email", help="owner's email (needed for reminders)")
    p.add_argument("--due", type=iso_date, help="YYYY-MM-DD")
    p.add_argument("--priority", default="Medium", help="High / Medium / Low (default Medium)")
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("update", parents=[common], help="change status / due date / priority / owner of tasks")
    p.add_argument("ids", nargs="+", help="one or more task IDs, e.g. T-012 T-013")
    p.add_argument("--status", help=f"one of: {', '.join(STATUSES)}")
    p.add_argument("--due", type=iso_date, help="new due date YYYY-MM-DD")
    p.add_argument("--priority", help="High / Medium / Low")
    p.add_argument("--owner")
    p.add_argument("--email")
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("reset", parents=[common], help="empty the task tracker (with backup) to start your own project")
    p.add_argument("--yes", action="store_true", help="confirm")
    p.set_defaults(func=cmd_reset)

    p = sub.add_parser("check", parents=[common], help="verify your setup (.env, Gemini key, Gmail login)")
    p.add_argument("--send-test", action="store_true", help="also send a test email to GMAIL_ADDRESS")
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("serve", parents=[common], help="browse generated emails at http://localhost:8765")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true", help="don't open a browser tab")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("demo", parents=[common], help="run the full workflow on the sample project")
    p.set_defaults(func=cmd_demo)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # never crash on non-ASCII names in a cp1252 console
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        print("\nNew here? Try: python main.py demo   then: python main.py serve")
        return 0
    settings = Settings.from_env()
    return args.func(args, settings)


if __name__ == "__main__":
    sys.exit(main())
