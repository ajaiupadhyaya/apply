"""Deadlines, follow-ups, and drafts that have gone quiet.

The digest exists to answer one question on a Monday morning: what needs my hands
this week? Everything it prints is something the owner can act on today.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from dataclasses import dataclass, field

from . import db
from .models import Row, Status

#: A draft nobody has looked at in this many days has probably been forgotten.
STALE_DAYS = 5
#: Submitted this long ago with no reply is worth a nudge.
SILENT_DAYS = 14
#: The deadline horizon the digest cares about.
HORIZON_DAYS = 14

OPEN_STATUSES = {
    Status.DRAFT.value, Status.GENERATED.value, Status.READY.value,
    Status.SUBMITTED.value, Status.ACKNOWLEDGED.value,
    Status.ASSESSMENT.value, Status.INTERVIEWING.value,
}


def _age_days(timestamp: str | None) -> int | None:
    if not timestamp:
        return None
    try:
        when = _dt.datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    return (_dt.datetime.now() - when).days


def headline(conn: sqlite3.Connection) -> dict[str, int]:
    """The four numbers across the top of the dashboard."""
    rows = [r for r in db.rows(conn) if r.application.status in OPEN_STATUSES]
    week_ago = _dt.datetime.now() - _dt.timedelta(days=7)

    submitted_week = 0
    for row in db.rows(conn):
        stamp = row.application.submitted_at
        if stamp:
            try:
                if _dt.datetime.fromisoformat(stamp) >= week_ago:
                    submitted_week += 1
            except ValueError:
                pass

    return {
        "due_7": sum(1 for r in rows if r.days_left is not None and 0 <= r.days_left <= 7),
        "awaiting_review": sum(1 for r in rows if r.application.status == Status.GENERATED.value),
        "ready": sum(1 for r in rows if r.application.status == Status.READY.value),
        "submitted_week": submitted_week,
        "no_deadline": sum(1 for r in rows if r.posting.deadline is None),
        "open": len(rows),
    }


@dataclass(slots=True)
class Digest:
    deadlines: list[Row] = field(default_factory=list)
    overdue: list[Row] = field(default_factory=list)
    followups: list[tuple] = field(default_factory=list)
    stale: list[Row] = field(default_factory=list)
    silent: list[Row] = field(default_factory=list)
    unverified: list[Row] = field(default_factory=list)
    beyond: list[Row] = field(default_factory=list)
    tracks: dict[str, int] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not any((self.deadlines, self.overdue, self.followups,
                        self.stale, self.silent, self.unverified, self.beyond))


def build(conn: sqlite3.Connection, horizon: int = HORIZON_DAYS) -> Digest:
    today = _dt.date.today()
    rows = db.rows(conn)
    open_rows = [r for r in rows if r.application.status in OPEN_STATUSES]
    result = Digest()

    for row in open_rows:
        left = row.days_left
        unsubmitted = row.application.status in (
            Status.DRAFT.value, Status.GENERATED.value, Status.READY.value)
        if left is None:
            if unsubmitted:
                result.unverified.append(row)
        elif left < 0 and unsubmitted:
            result.overdue.append(row)
        elif 0 <= left <= horizon:
            result.deadlines.append(row)
        elif unsubmitted:
            # Past the horizon, but an unsubmitted deadline should never be
            # invisible just because it is not urgent yet.
            result.beyond.append(row)

        if unsubmitted:
            age = _age_days(row.posting.created_at)
            if age is not None and age >= STALE_DAYS:
                result.stale.append(row)

        if row.application.status == Status.SUBMITTED.value:
            age = _age_days(row.application.submitted_at)
            if age is not None and age >= SILENT_DAYS:
                result.silent.append(row)

    for row in rows:
        for f in db.followups(conn, row.application.id):
            if f.due_on <= today + _dt.timedelta(days=horizon):
                result.followups.append((f, row))
    result.followups.sort(key=lambda pair: pair[0].due_on)

    for row in open_rows:
        result.tracks[row.posting.track] = result.tracks.get(row.posting.track, 0) + 1
    return result


def render(conn: sqlite3.Connection, console, horizon: int = HORIZON_DAYS) -> None:
    from rich.markup import escape as esc
    from rich.table import Table

    counts = headline(conn)
    d = build(conn, horizon)

    console.print(
        f"\n[bold red]{counts['due_7']}[/] due ≤7d   "
        f"[yellow]{counts['awaiting_review']}[/] awaiting review   "
        f"[bold green]{counts['ready']}[/] ready to submit   "
        f"[cyan]{counts['submitted_week']}[/] submitted this week\n"
    )

    def section(title: str, rows, formatter) -> None:
        if not rows:
            return
        console.print(f"[bold]{title}[/]")
        for item in rows:
            console.print(f"  {formatter(item)}")
        console.print()

    section("Past due, not submitted", d.overdue,
            lambda r: f"[bold red]{r.posting.deadline}[/]  {esc(r.posting.company)} — "
                      f"{esc(r.posting.role)}  [dim]({-r.days_left}d ago, {esc(r.application.status)})[/]")

    def urgency(row) -> str:
        """A style name, or the empty string. Never an empty [] tag: Rich reads
        that as a closing tag with nothing to close and raises."""
        if row.days_left <= 3:
            return "bold red"
        return "yellow" if row.days_left <= 7 else ""

    def deadline_line(row) -> str:
        style = urgency(row)
        when = f"[{style}]{row.posting.deadline}[/]" if style else str(row.posting.deadline)
        return (f"{when}  {esc(row.posting.company)} — {esc(row.posting.role)}  "
                f"[dim]({row.days_left}d, {esc(row.application.status)})[/]")

    section(f"Deadlines in the next {horizon} days", d.deadlines, deadline_line)

    section("Follow-ups due", d.followups,
            lambda pair: f"[dim]{pair[0].due_on}[/]  {esc(pair[1].posting.company)}: {esc(pair[0].action)}")

    section(f"Drafts untouched for {STALE_DAYS}+ days", d.stale,
            lambda r: f"{esc(r.posting.company)} — {esc(r.posting.role)}  [dim]({esc(r.application.status)})[/]")

    section(f"Submitted {SILENT_DAYS}+ days ago, no reply", d.silent,
            lambda r: f"{esc(r.posting.company)} — {esc(r.posting.role)}  "
                      f"[dim]sent {(r.application.submitted_at or '')[:10]}[/]")

    section("Further out, not yet submitted", d.beyond,
            lambda r: f"[dim]{r.posting.deadline}[/]  {esc(r.posting.company)} — "
                      f"{esc(r.posting.role)}  [dim]({r.days_left}d, {esc(r.application.status)})[/]")

    section("No deadline on file — verify manually", d.unverified,
            lambda r: f"[yellow]⚠[/]  {esc(r.posting.company)} — {esc(r.posting.role)}")

    if d.tracks:
        console.print("[bold]Open pipeline by track[/]")
        width = max(d.tracks.values())
        table = Table(box=None, show_header=False, padding=(0, 2))
        for track, n in sorted(d.tracks.items(), key=lambda kv: -kv[1]):
            table.add_row(track, "█" * round(18 * n / width), str(n))
        console.print(table)

    if d.empty:
        console.print("[green]Nothing needs your hands this week.[/]")
