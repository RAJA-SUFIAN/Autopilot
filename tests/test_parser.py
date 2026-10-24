from datetime import date

from conftest import ROOT
from pm_autopilot import parser
from pm_autopilot.parser import GeminiError, parse_action_line, parse_attendees, parse_meeting, parse_rules

NOTES = """TITLE: Sprint Review
DATE: 2026-10-22
ATTENDEES: Ali Hassan <ali@example.com>, Noura Al-Harbi (noura@example.com), guest@example.com
SUMMARY: Good sprint.
DECISION: Ship on Thursday.
- DECISION: Freeze scope.
ACTION: Ali - finish API docs - 2026-11-05
ACTION: Noura Al-Harbi - add timer - High - 2026-11-04
* action: Bob - review pricing - next week
"""


def test_parse_attendees_formats():
    people = parse_attendees("Ali Hassan <ali@example.com>, Noura (noura@example.com), x@example.com, Bob")
    assert [(p.name, p.email) for p in people] == [
        ("Ali Hassan", "ali@example.com"), ("Noura", "noura@example.com"), ("x", "x@example.com"), ("Bob", ""),
    ]


def test_parse_rules_extracts_everything():
    m = parse_rules(NOTES, "sprint_review.txt")
    assert m.title == "Sprint Review"
    assert m.date == date(2026, 10, 22)
    assert m.summary == "Good sprint."
    assert m.decisions == ["Ship on Thursday.", "Freeze scope."]
    assert len(m.action_items) == 3

    ali, noura, bob = m.action_items
    assert (ali.task, ali.owner, ali.owner_email, ali.due_date, ali.priority) == (
        "Finish API docs", "Ali Hassan", "ali@example.com", date(2026, 11, 5), "Medium")
    assert (noura.owner_email, noura.priority, noura.due_date) == ("noura@example.com", "High", date(2026, 11, 4))
    # Unknown owner and an unparseable date are kept as part of the task, not lost
    assert (bob.owner, bob.owner_email, bob.due_date) == ("Bob", "", None)
    assert bob.task == "Review pricing - next week"


def test_task_may_contain_spaced_dashes():
    item = parse_action_line("Ali - migrate DB - phase 2 - 2026-11-01 - low", [])
    assert (item.task, item.due_date, item.priority) == ("Migrate DB - phase 2", date(2026, 11, 1), "Low")


def test_action_without_task_is_skipped():
    assert parse_action_line("Ali", []) is None


def test_summary_falls_back_to_body_and_title_to_filename():
    m = parse_rules("We reviewed the roadmap.\nBudget is fine.\n", "weekly_sync.txt")
    assert m.title == "Weekly Sync"
    assert m.summary == "We reviewed the roadmap. Budget is fine."


def test_uses_rules_without_api_key(settings, monkeypatch):
    monkeypatch.setattr(parser, "call_gemini", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no call")))
    m = parse_meeting(ROOT / "meetings" / "sprint_review.txt", settings)
    assert m.parser == "rules" and len(m.action_items) == 6


def test_gemini_result_is_used_and_emails_resolved(settings, tmp_path, monkeypatch):
    settings.gemini_api_key = "test-key"
    notes = tmp_path / "n.txt"
    notes.write_text("ATTENDEES: Ali Hassan <ali@example.com>\nAli will send the docs by Nov 5th.", encoding="utf-8")
    monkeypatch.setattr(parser, "call_gemini", lambda prompt, s: {
        "title": "Docs sync", "date": "2026-10-22", "summary": "Short.", "decisions": ["Use OpenAPI"],
        "attendees": [{"name": "Ali Hassan", "email": "wrong@guess.com"}],
        "action_items": [{"task": "Send the docs", "owner": "Ali Hassan", "owner_email": "",
                          "due_date": "2026-11-05", "priority": "urgent"}],
    })
    m = parse_meeting(notes, settings)
    assert m.parser == "gemini"
    assert m.attendees[0].email == "ali@example.com"  # notes beat the model's guess
    item = m.action_items[0]
    assert (item.owner_email, item.due_date, item.priority) == ("ali@example.com", date(2026, 11, 5), "High")


def test_gemini_failure_falls_back_to_rules(settings, monkeypatch):
    settings.gemini_api_key = "test-key"

    def boom(*args, **kwargs):
        raise GeminiError("quota exceeded")

    monkeypatch.setattr(parser, "call_gemini", boom)
    m = parse_meeting(ROOT / "meetings" / "sprint_review.txt", settings)
    assert m.parser == "rules" and len(m.action_items) == 6
