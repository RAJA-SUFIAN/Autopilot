"""Find tasks that are overdue or due soon and build one reminder email per owner."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import date

from .config import Settings
from .emails import reminder_email
from .models import Email
from .tracker import Task

log = logging.getLogger(__name__)


def find_due_tasks(tasks: list[Task], today: date, window_days: int = 2) -> list[Task]:
    """Open tasks that are overdue or due within `window_days` (inclusive)."""
    return sorted(
        (t for t in tasks if not t.is_done and t.due_date and t.days_until_due(today) <= window_days),
        key=lambda t: (t.due_date, t.id),
    )


def build_reminders(tasks: list[Task], today: date, settings: Settings, window_days: int = 2) -> list[Email]:
    by_owner: dict[str, list[Task]] = defaultdict(list)
    for task in find_due_tasks(tasks, today, window_days):
        if task.email:
            by_owner[task.email.lower()].append(task)
        else:
            log.warning("%s (%s) has no owner email - cannot send a reminder.", task.id, task.owner)
    return [reminder_email(owned[0].owner, address, owned, today, settings) for address, owned in by_owner.items()]
