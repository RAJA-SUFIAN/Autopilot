from datetime import date, timedelta

from conftest import TODAY, make_task
from pm_autopilot.reminders import build_reminders, find_due_tasks
from pm_autopilot.report import build_report, rag_status


def days(n: int) -> date:
    return TODAY + timedelta(days=n)


def test_find_due_tasks_window():
    tasks = [
        make_task(id="T-1", due=days(-5)),                 # overdue
        make_task(id="T-2", due=days(0)),                  # today
        make_task(id="T-3", due=days(2)),                  # edge of window
        make_task(id="T-4", due=days(3)),                  # outside
        make_task(id="T-5", due=days(-1), status="Done"),  # done
        make_task(id="T-6", due=None),                     # no date
    ]
    assert [t.id for t in find_due_tasks(tasks, TODAY)] == ["T-1", "T-2", "T-3"]
    assert [t.id for t in find_due_tasks(tasks, TODAY, window_days=3)] == ["T-1", "T-2", "T-3", "T-4"]


def test_one_reminder_per_owner_and_skip_missing_email(settings):
    tasks = [
        make_task(id="T-1", owner="Ali", email="ali@example.com", due=days(-2)),
        make_task(id="T-2", owner="Ali", email="ALI@example.com", due=days(1)),
        make_task(id="T-3", owner="Noura", email="noura@example.com", due=days(1)),
        make_task(id="T-4", owner="Ghost", email="", due=days(-1)),
    ]
    emails = build_reminders(tasks, TODAY, settings)
    assert [e.to for e in emails] == [["ali@example.com"], ["noura@example.com"]]
    assert emails[0].subject.startswith("[Overdue] 1 task needs attention")
    assert "T-1" in emails[0].html and "T-2" in emails[0].html
    assert emails[1].subject.startswith("[Reminder] 1 task due soon")


def test_rag_thresholds():
    high = make_task(priority="High", due=days(-1))
    low = make_task(priority="Low", due=days(-1))
    assert rag_status(10, [])[0] == "Green"
    assert rag_status(20, [low])[0] == "Green"            # 5%
    assert rag_status(20, [high])[0] == "Amber"           # any High overdue
    assert rag_status(10, [low, low])[0] == "Amber"       # 20%
    assert rag_status(10, [low, low, low])[0] == "Red"    # 30%


def test_build_report_counts():
    tasks = [
        make_task(id="T-1", status="Done", due=days(-10)),
        make_task(id="T-2", status="In Progress", due=days(-3), priority="High"),
        make_task(id="T-3", status="In Progress", due=days(4)),
        make_task(id="T-4", status="Blocked", due=days(9)),
        make_task(id="T-5", status="Not Started"),
    ]
    r = build_report(tasks, TODAY)
    assert (r.total, r.done, r.in_progress, r.blocked, r.not_started) == (5, 1, 2, 1, 1)
    assert [t.id for t in r.overdue] == ["T-2"]
    assert [t.id for t in r.due_next_week] == ["T-3"]
    assert r.completion_pct == 20
    assert r.rag == "Amber"  # 1 of 4 open overdue = 25% (not above the Red line), but it is High priority
    assert r.week_start == date(2026, 10, 19)
