import shutil
from datetime import date

from conftest import ROOT, TODAY, make_task
from pm_autopilot.models import ActionItem
from pm_autopilot.parser import parse_rules
from pm_autopilot.tracker import TaskTracker


def test_add_assigns_ids_and_persists(tmp_path):
    tracker = TaskTracker(tmp_path / "tasks.csv")
    matched, added = tracker.add_action_items(
        [ActionItem("Write docs", "Ali", "ali@example.com", date(2026, 11, 5), "High"),
         ActionItem("Test app", "Noura", "noura@example.com")],
        "m.txt",
    )
    assert [t.id for t in added] == ["T-001", "T-002"] and matched == added
    loaded = tracker.load()
    assert [(t.task, t.status, t.due_date, t.source_meeting) for t in loaded] == [
        ("Write docs", "Not Started", date(2026, 11, 5), "m.txt"),
        ("Test app", "Not Started", None, "m.txt"),
    ]


def test_duplicates_are_skipped_case_and_punctuation_insensitive(tmp_path):
    tracker = TaskTracker(tmp_path / "tasks.csv")
    tracker.add_action_items([ActionItem("Write docs", "Ali")], "a.txt")
    matched, added = tracker.add_action_items(
        [ActionItem("write  DOCS.", "ali"), ActionItem("Write docs", "Noura"), ActionItem("Write docs", "Noura")],
        "b.txt",
    )
    assert [t.owner for t in added] == ["Noura"]
    assert [t.id for t in matched] == ["T-001", "T-002"]
    assert len(tracker.load()) == 2


def test_ids_continue_after_existing_max(tmp_path):
    tracker = TaskTracker(tmp_path / "tasks.csv")
    tracker.save([make_task(id="T-007")])
    _, added = tracker.add_action_items([ActionItem("New one", "Ali")], "m.txt")
    assert added[0].id == "T-008"


def test_overdue_logic():
    assert make_task(due=date(2026, 10, 23)).is_overdue(TODAY)
    assert not make_task(due=date(2026, 10, 23), status="Done").is_overdue(TODAY)
    assert not make_task(due=TODAY).is_overdue(TODAY)
    assert not make_task(due=None).is_overdue(TODAY)


def test_sample_data_is_consistent_with_sample_meetings(tmp_path):
    """Kickoff + stakeholder notes are fully tracked already; sprint review adds 4 of its 6 items."""
    csv_copy = tmp_path / "tasks.csv"
    shutil.copy(ROOT / "data" / "tasks.csv", csv_copy)
    tracker = TaskTracker(csv_copy)
    assert len(tracker.load()) == 20
    for name, expected_new in [("project_kickoff.txt", 0), ("stakeholder_sync.txt", 0), ("sprint_review.txt", 4)]:
        meeting = parse_rules((ROOT / "meetings" / name).read_text(encoding="utf-8"), name)
        _, added = tracker.add_action_items(meeting.action_items, name)
        assert len(added) == expected_new, name
    assert all(t.email for t in tracker.load())
