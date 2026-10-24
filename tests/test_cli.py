"""End-to-end CLI tests: run main() against a temporary tracker and outbox."""
import shutil
import socket
from datetime import date

import pytest

import main
from conftest import ROOT
from pm_autopilot.server import make_server
from pm_autopilot.tracker import TaskTracker, normalize_status


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    csv_path = tmp_path / "tasks.csv"
    shutil.copy(ROOT / "data" / "tasks.csv", csv_path)
    for name in ("GEMINI_API_KEY", "SEND_EMAILS", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD", "REPORT_RECIPIENTS"):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("TASKS_CSV", str(csv_path))
    monkeypatch.setenv("OUTBOX_DIR", str(tmp_path / "outbox"))
    return tmp_path


def test_normalize_status():
    assert normalize_status("done") == "Done"
    assert normalize_status("in-progress") == "In Progress"
    assert normalize_status("NOT_STARTED") == "Not Started"
    assert normalize_status("finished") is None


def test_demo_runs_end_to_end(workspace):
    assert main.main(["demo", "--today", "2026-10-24"]) == 0
    outbox = workspace / "outbox"
    assert len(list(outbox.glob("*.html"))) == 16  # 15 emails + index.html
    assert len(TaskTracker(workspace / "tasks.csv").load()) == 24


def test_add_reuses_known_owner_and_skips_duplicates(workspace, capsys):
    assert main.main(["add", "Book launch venue", "--owner", "Sara", "--due", "2026-11-20", "--priority", "high"]) == 0
    task = TaskTracker(workspace / "tasks.csv").load()[-1]
    assert (task.id, task.owner, task.email, task.priority, task.due_date) == (
        "T-021", "Sara Al-Qahtani", "sara.alqahtani@example.com", "High", date(2026, 11, 20))
    assert main.main(["add", "book launch venue", "--owner", "Sara Al-Qahtani"]) == 0
    assert "Already tracked as T-021" in capsys.readouterr().out
    assert main.main(["add", "X", "--owner", "A", "--priority", "huge"]) == 1


def test_update_status_and_due(workspace, capsys):
    assert main.main(["update", "t-012", "T-014", "--status", "done"]) == 0
    tasks = {t.id: t for t in TaskTracker(workspace / "tasks.csv").load()}
    assert tasks["T-012"].status == tasks["T-014"].status == "Done"
    assert main.main(["update", "T-008", "--due", "2026-11-01"]) == 0
    assert TaskTracker(workspace / "tasks.csv").load()[7].due_date == date(2026, 11, 1)
    assert main.main(["update", "T-999", "--status", "done"]) == 1
    assert main.main(["update", "T-001", "--status", "finished"]) == 1
    assert main.main(["update", "T-001"]) == 1


def test_reset_needs_confirmation_and_keeps_backup(workspace):
    assert main.main(["reset"]) == 1
    assert len(TaskTracker(workspace / "tasks.csv").load()) == 20
    assert main.main(["reset", "--yes"]) == 0
    assert TaskTracker(workspace / "tasks.csv").load() == []
    backups = list(workspace.glob("tasks.backup-*.csv"))
    assert len(backups) == 1 and len(TaskTracker(backups[0]).load()) == 20


def test_check_passes_in_demo_mode(workspace, capsys):
    assert main.main(["check"]) == 0
    out = capsys.readouterr().out
    assert "DEMO MODE" in out and "rule-based parser" in out


def test_comment_lines_in_notes_are_ignored(workspace):
    notes = workspace / "notes.txt"
    notes.write_text("# a comment\nACTION: Ali - Write docs - 2026-11-01\n", encoding="utf-8")
    assert main.main(["process", str(notes), "--no-emails"]) == 0


class _FakeTTY:
    def isatty(self):
        return True


@pytest.fixture
def smtp_workspace(workspace, monkeypatch):
    """Real-sending mode with SMTP replaced by a recorder - nothing touches the network."""
    monkeypatch.setenv("SEND_EMAILS", "true")
    monkeypatch.setenv("GMAIL_ADDRESS", "me@gmail.com")
    monkeypatch.setenv("GMAIL_APP_PASSWORD", "abcd efgh ijkl mnop")
    sent = []
    monkeypatch.setattr(main.Mailer, "_send_smtp", lambda self, emails: sent.extend(emails) or ["sent"] * len(emails))
    return sent


def test_real_sending_is_refused_without_terminal_or_yes(smtp_workspace, capsys):
    assert main.main(["reminders", "--today", "2026-10-24"]) == 0
    assert smtp_workspace == []
    assert "Add --yes" in capsys.readouterr().err


def test_real_sending_with_yes_flag(smtp_workspace):
    assert main.main(["reminders", "--today", "2026-10-24", "--yes"]) == 0
    assert len(smtp_workspace) == 6


@pytest.mark.parametrize("answer, expected", [("y", 6), ("n", 0), ("", 0)])
def test_real_sending_asks_first(smtp_workspace, monkeypatch, capsys, answer, expected):
    monkeypatch.setattr("sys.stdin", _FakeTTY())
    monkeypatch.setattr("builtins.input", lambda prompt: answer)
    main.main(["reminders", "--today", "2026-10-24"])
    assert len(smtp_workspace) == expected
    assert "About to SEND 6 real email(s)" in capsys.readouterr().out


def test_demo_mode_never_asks(workspace, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: pytest.fail("should not prompt in demo mode"))
    assert main.main(["reminders", "--today", "2026-10-24"]) == 0


def test_server_moves_to_next_free_port():
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen()
    taken = blocker.getsockname()[1]
    try:
        server = make_server(ROOT, taken)
        assert server.server_address[1] != taken
        server.server_close()
    finally:
        blocker.close()
