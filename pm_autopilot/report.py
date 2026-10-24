"""Weekly status report: counts, overdue list and a simple RAG (Red/Amber/Green) rating."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta

from .tracker import Task

# RAG thresholds on the share of open tasks that are overdue.
AMBER_THRESHOLD = 0.10
RED_THRESHOLD = 0.25


@dataclass
class OwnerLoad:
    owner: str
    open: int = 0
    done: int = 0
    overdue: int = 0


@dataclass
class StatusReport:
    today: date
    total: int
    done: int
    in_progress: int
    not_started: int
    blocked: int
    overdue: list[Task]
    due_next_week: list[Task]
    rag: str
    rag_reason: str
    by_owner: list[OwnerLoad] = field(default_factory=list)

    @property
    def week_start(self) -> date:
        return self.today - timedelta(days=self.today.weekday())

    @property
    def open(self) -> int:
        return self.total - self.done

    @property
    def completion_pct(self) -> int:
        return round(100 * self.done / self.total) if self.total else 0


def rag_status(open_count: int, overdue: list[Task]) -> tuple[str, str]:
    """Red if >25% of open work is overdue; Amber if >10% or any High-priority task is overdue; else Green."""
    if not open_count or not overdue:
        return "Green", "No overdue tasks - delivery is on track."
    ratio = len(overdue) / open_count
    high = sum(1 for t in overdue if t.priority == "High")
    detail = (f"{len(overdue)} of {open_count} open tasks are overdue ({ratio:.0%})"
              + (f", {high} of them High priority." if high else "."))
    if ratio > RED_THRESHOLD:
        return "Red", detail + " Delivery is at risk - recovery plan needed this week."
    if ratio > AMBER_THRESHOLD or high:
        return "Amber", detail + " Manageable, but needs owner attention to avoid slippage."
    return "Green", detail + " Minor slippage, overall on track."


def build_report(tasks: list[Task], today: date) -> StatusReport:
    status = lambda name: sum(1 for t in tasks if t.status.lower() == name)  # noqa: E731
    overdue = sorted((t for t in tasks if t.is_overdue(today)), key=lambda t: (t.due_date, t.id))
    due_next_week = sorted(
        (t for t in tasks if not t.is_done and t.due_date and 0 <= t.days_until_due(today) <= 7),
        key=lambda t: (t.due_date, t.id),
    )
    loads: dict[str, OwnerLoad] = defaultdict(lambda: OwnerLoad(""))
    for t in tasks:
        load = loads[t.owner]
        load.owner = t.owner
        if t.is_done:
            load.done += 1
        else:
            load.open += 1
            load.overdue += t.is_overdue(today)
    done = status("done")
    rag, reason = rag_status(len(tasks) - done, overdue)
    return StatusReport(
        today=today, total=len(tasks), done=done, in_progress=status("in progress"),
        not_started=status("not started"), blocked=status("blocked"),
        overdue=overdue, due_next_week=due_next_week, rag=rag, rag_reason=reason,
        by_owner=sorted(loads.values(), key=lambda o: (-o.overdue, -o.open, o.owner)),
    )
