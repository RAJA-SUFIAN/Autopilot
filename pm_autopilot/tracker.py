"""CSV-backed task tracker (data/tasks.csv)."""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .models import ActionItem, parse_date

FIELDS = ["id", "task", "owner", "email", "due_date", "priority", "status", "source_meeting"]
STATUSES = ("Not Started", "In Progress", "Blocked", "Done")


@dataclass
class Task:
    id: str
    task: str
    owner: str
    email: str
    due_date: date | None
    priority: str
    status: str
    source_meeting: str

    @property
    def is_done(self) -> bool:
        return self.status.strip().lower() == "done"

    def days_until_due(self, today: date) -> int | None:
        return (self.due_date - today).days if self.due_date else None

    def is_overdue(self, today: date) -> bool:
        return not self.is_done and self.due_date is not None and self.due_date < today

    @property
    def key(self) -> tuple[str, str]:
        return dedupe_key(self.task, self.owner)

    @classmethod
    def from_row(cls, row: dict) -> "Task":
        return cls(
            id=row.get("id", "").strip(),
            task=row.get("task", "").strip(),
            owner=row.get("owner", "").strip(),
            email=row.get("email", "").strip(),
            due_date=parse_date(row.get("due_date")),
            priority=row.get("priority", "").strip() or "Medium",
            status=row.get("status", "").strip() or "Not Started",
            source_meeting=row.get("source_meeting", "").strip(),
        )

    def to_row(self) -> dict:
        return {
            "id": self.id, "task": self.task, "owner": self.owner, "email": self.email,
            "due_date": self.due_date.isoformat() if self.due_date else "",
            "priority": self.priority, "status": self.status, "source_meeting": self.source_meeting,
        }


def normalize_status(value: str) -> str | None:
    """Accept 'done', 'in-progress', 'IN_PROGRESS', 'not started'... and return the canonical status."""
    key = re.sub(r"[\s_-]+", "", value.lower())
    return next((s for s in STATUSES if s.replace(" ", "").lower() == key), None)


def dedupe_key(task: str, owner: str) -> tuple[str, str]:
    """Case/punctuation-insensitive identity of a task, so re-processing notes never duplicates rows."""
    norm = lambda s: re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", s.lower())).strip()  # noqa: E731
    return norm(task), norm(owner)


class TaskTracker:
    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> list[Task]:
        if not self.path.exists():
            return []
        with self.path.open(newline="", encoding="utf-8") as fh:
            return [Task.from_row(row) for row in csv.DictReader(fh) if any((v or "").strip() for v in row.values())]

    def save(self, tasks: list[Task]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDS)
            writer.writeheader()
            writer.writerows(t.to_row() for t in tasks)

    def known_owner(self, owner: str, email: str = "") -> tuple[str, str]:
        """Match a typed owner ("Sara", or an email) to an existing owner so names/emails stay consistent."""
        people = {(t.owner, t.email) for t in self.load() if t.owner}
        if email:
            match = next((p for p in people if p[1].lower() == email.lower()), None)
            return (match[0], match[1]) if match else (owner, email)
        exact = [p for p in people if p[0].lower() == owner.lower() and p[1]]
        if exact:
            return exact[0]
        first = [p for p in people if p[1] and p[0].lower().split()[:1] == owner.lower().split()[:1]]
        if len({p[0] for p in first}) == 1:  # only when the first name is unambiguous
            return first[0]
        return owner, email

    def update(self, task_ids: list[str], **changes) -> tuple[list[Task], list[str]]:
        """Apply field changes (status, due_date, priority, owner, email) to tasks by ID.

        Returns (updated tasks, IDs that were not found). IDs are case-insensitive.
        """
        tasks = self.load()
        by_id = {t.id.upper(): t for t in tasks}
        updated, missing = [], []
        for task_id in task_ids:
            task = by_id.get(task_id.strip().upper())
            if task is None:
                missing.append(task_id)
                continue
            for field_name, value in changes.items():
                if value is not None:
                    setattr(task, field_name, value)
            updated.append(task)
        if updated:
            self.save(tasks)
        return updated, missing

    def add_action_items(self, items: list[ActionItem], source_meeting: str) -> tuple[list[Task], list[Task]]:
        """Append new action items, skipping ones already tracked.

        Returns (tasks matching `items` in order - new or existing, newly added subset).
        """
        tasks = self.load()
        by_key = {t.key: t for t in tasks}
        next_num = max((int(m[1]) for t in tasks if (m := re.match(r"T-(\d+)$", t.id))), default=0) + 1
        matched, added = [], []
        for item in items:
            key = dedupe_key(item.task, item.owner)
            task = by_key.get(key)
            if task is None:
                task = Task(
                    id=f"T-{next_num:03d}", task=item.task, owner=item.owner, email=item.owner_email,
                    due_date=item.due_date, priority=item.priority, status="Not Started",
                    source_meeting=source_meeting,
                )
                next_num += 1
                tasks.append(task)
                by_key[key] = task
                added.append(task)
            if task not in matched:
                matched.append(task)
        if added:
            self.save(tasks)
        return matched, added
