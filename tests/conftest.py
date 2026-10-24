import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pm_autopilot.config import Settings  # noqa: E402
from pm_autopilot.tracker import Task  # noqa: E402

TODAY = date(2026, 10, 24)


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(tasks_csv=tmp_path / "tasks.csv", outbox_dir=tmp_path / "outbox")


def make_task(id="T-001", task="Do the thing", owner="Ali Hassan", email="ali@example.com",
              due=None, priority="Medium", status="Not Started") -> Task:
    return Task(id, task, owner, email, due, priority, status, "test.txt")
