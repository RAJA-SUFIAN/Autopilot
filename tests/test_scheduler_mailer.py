from datetime import date, datetime, timezone

import pytest

from conftest import TODAY, make_task
from pm_autopilot.emails import followup_emails, invite_email, mom_email
from pm_autopilot.mailer import Mailer, html_to_text
from pm_autopilot.models import Attendee, Meeting
from pm_autopilot.scheduler import Invite, build_ics, fold, parse_utc_offset


def make_invite(**overrides) -> Invite:
    values = dict(title="Sprint Planning; Q4, kickoff", start=datetime(2026, 11, 2, 10, 0),
                  attendees=["a@x.com", "b@x.com"], duration_minutes=90, agenda=["Retro", "Backlog"],
                  uid="fixed@pm-autopilot")
    values.update(overrides)
    return Invite(**values)


def test_ics_contents():
    ics = build_ics(make_invite(), now=datetime(2026, 10, 24, 12, 0, tzinfo=timezone.utc))
    unfolded = ics.replace("\r\n ", "")
    assert ics.startswith("BEGIN:VCALENDAR\r\n") and ics.endswith("END:VCALENDAR\r\n")
    assert "DTSTART:20261102T070000Z" in unfolded   # 10:00 Riyadh (+03:00) = 07:00 UTC
    assert "DTEND:20261102T083000Z" in unfolded
    assert "SUMMARY:Sprint Planning\\; Q4\\, kickoff" in unfolded
    assert "DESCRIPTION:Agenda:\\n1. Retro\\n2. Backlog" in unfolded
    assert unfolded.count("ATTENDEE;") == 2 and "mailto:b@x.com" in unfolded
    assert all(len(line.encode()) <= 75 for line in ics.split("\r\n"))


def test_fold_respects_utf8_boundaries():
    line = "SUMMARY:" + "مواقف" * 30  # Arabic text, 2 bytes per char
    folded = fold(line)
    assert folded.replace("\r\n ", "") == line
    assert all(len(part.encode()) <= 75 for part in folded.split("\r\n"))


def test_utc_offset_parsing():
    assert parse_utc_offset("+03:00").utcoffset(None).total_seconds() == 3 * 3600
    assert parse_utc_offset("-0530").utcoffset(None).total_seconds() == -5.5 * 3600
    with pytest.raises(ValueError):
        parse_utc_offset("Riyadh")


def make_meeting() -> Meeting:
    return Meeting(
        title="Sprint <Review>", source="s.txt", date=date(2026, 10, 22),
        attendees=[Attendee("Ali Hassan", "ali@example.com"), Attendee("Noura", "noura@example.com"), Attendee("Guest")],
        summary="All good & on track.", decisions=["Ship it"],
    )


def test_mom_and_followups(settings):
    tasks = [make_task(id="T-1", owner="Ali Hassan", email="ali@example.com", due=TODAY),
             make_task(id="T-2", owner="Ali Hassan", email="ali@example.com"),
             make_task(id="T-3", owner="Noura", email="noura@example.com")]
    mom = mom_email(make_meeting(), tasks, settings)
    assert mom.to == ["ali@example.com", "noura@example.com"]
    assert "Sprint &lt;Review&gt;" in mom.html and "All good &amp; on track." in mom.html  # escaped
    followups = followup_emails(make_meeting(), tasks, settings)
    assert [(f.to, f.subject.split(" from")[0]) for f in followups] == [
        (["ali@example.com"], "[Action required] Your 2 tasks"),
        (["noura@example.com"], "[Action required] Your 1 task"),
    ]


def test_demo_mode_writes_outbox(settings):
    invite = make_invite()
    email = invite_email(invite, build_ics(invite), settings)
    results = Mailer(settings).deliver([email])
    saved = settings.outbox_dir / "invite__sprint-planning-q4-kickoff-mon-02-nov-2026-10-00.html"
    assert results == [str(saved)]
    assert "DEMO MODE - not sent." in saved.read_text(encoding="utf-8")
    assert (settings.outbox_dir / f"{invite.slug}.ics").read_text(encoding="utf-8").startswith("BEGIN:VCALENDAR")
    index = (settings.outbox_dir / "index.html").read_text(encoding="utf-8")
    assert saved.name in index and "Sprint Planning; Q4, kickoff" in index and "a@x.com, b@x.com" in index


def test_send_without_credentials_stays_in_demo_mode(settings):
    settings.send_emails = True
    assert Mailer(settings).mode == "demo"
    settings.gmail_address, settings.gmail_app_password = "me@gmail.com", "abcd"
    assert Mailer(settings).mode == "smtp"


def test_smtp_message_has_text_html_and_calendar_parts(settings):
    settings.gmail_address = "me@gmail.com"
    invite = make_invite()
    msg = Mailer(settings).build_message(invite_email(invite, build_ics(invite), settings))
    types = [part.get_content_type() for part in msg.walk()]
    assert {"text/plain", "text/html", "text/calendar"} <= set(types)
    assert msg["To"] == "a@x.com, b@x.com"


def test_unaddressed_emails_are_skipped(settings):
    mom = mom_email(Meeting(title="Solo", source="x.txt"), [], settings)
    assert Mailer(settings).deliver([mom]) == []


def test_html_to_text():
    assert html_to_text("<title>T</title><p>Hello&nbsp;<b>Ali</b></p><br>Bye") == "Hello\xa0Ali\n\nBye\n"
