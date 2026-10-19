"""Is each posting you have not yet sent still open where it was found?

A posting filed three weeks ago may have closed since: a letter written for it
is money and an evening spent on nothing. The sweep re-reads each open,
unsubmitted posting's own URL, by GET, and sorts the answer three ways:

    closed       positive evidence it is gone: 404 or 410, a redirect from the
                 posting back up to the board, or the page saying so
    unreachable  nothing is known: a timeout, 401/403, 429, a 5xx
    open         the page is there

Only `closed` is recorded, as an event, and it changes no status — whether to
withdraw is the owner's call. A later sweep that finds the page again clears it.
The distinction between closed and unreachable is ai-job-search's (/rank): a
blocked request is a rejected client, not a missing posting.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Callable

import httpx

from . import db
from .models import Row, Status

#: Unsubmitted statuses: something could still be written or sent for these.
SWEPT = (Status.DRAFT.value, Status.GENERATED.value, Status.READY.value)

CLOSED_EVENT = "source_closed"
OPEN_EVENT = "source_open"

#: What a careers page says when the requisition is gone. Lowercased substrings.
_CLOSED_PHRASES = re.compile(
    r"no longer (?:available|accepting applications|open|active|posted)"
    r"|(?:position|role|job|posting|requisition) has (?:been filled|been closed|closed|expired)"
    r"|(?:this|the) (?:job|position|posting) (?:has )?(?:expired|is closed)"
    r"|job you are looking for (?:is|was) (?:no longer|not found)"
    r"|page you are looking for (?:doesn.t|does not) exist",
    re.I,
)


@dataclass(slots=True)
class Result:
    state: str          # open | closed | unreachable
    reason: str = ""


def _client() -> httpx.Client:
    from .sources.ats import TIMEOUT, USER_AGENT

    return httpx.Client(timeout=TIMEOUT, follow_redirects=True,
                        headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*"})


def _redirected_up(original: httpx.URL, final: httpx.URL) -> bool:
    """The posting's URL sent us to the board above it: the requisition is gone."""
    before, after = original.path.rstrip("/"), final.path.rstrip("/")
    if before == after:
        return False
    return before.startswith(after) or "error" in str(final.query).lower()


def check(url: str, *, client: Callable[[], httpx.Client] = _client) -> Result:
    from .sources.ats import workday_posting_state

    try:
        with client() as http:
            # A Workday job page is a JavaScript shell that loads whether or not
            # the job exists. Ask the API it renders from instead.
            workday = workday_posting_state(http, url)
            if workday is not None:
                return Result(*workday)
            response = http.get(url)
    except httpx.HTTPError as exc:
        return Result("unreachable", f"{type(exc).__name__}")
    if response.status_code in (404, 410):
        return Result("closed", f"HTTP {response.status_code}")
    if response.status_code >= 400:
        return Result("unreachable", f"HTTP {response.status_code}")
    if response.history and _redirected_up(httpx.URL(url), response.url):
        return Result("closed", f"redirect to {response.url}")
    found = _CLOSED_PHRASES.search(response.text or "")
    if found:
        return Result("closed", f'the page says "{found.group(0)}"')
    return Result("open")


def closed_at_source(conn: sqlite3.Connection, app_id: int) -> str | None:
    """The reason from the latest sweep, if that sweep found the posting closed."""
    for event in db.events(conn, app_id):           # newest first
        if event.kind == CLOSED_EVENT:
            return event.detail or "closed"
        if event.kind == OPEN_EVENT:
            return None
    return None


@dataclass(slots=True)
class Report:
    checked: int = 0
    closed: list[tuple[Row, Result]] = field(default_factory=list)
    unreachable: list[tuple[Row, Result]] = field(default_factory=list)
    reopened: list[Row] = field(default_factory=list)


def candidates(conn: sqlite3.Connection) -> list[Row]:
    from .digest import in_pipeline

    return [r for r in db.rows(conn, SWEPT)
            if in_pipeline(r) and (r.posting.source_url or "").startswith(("http://", "https://"))]


def run(conn: sqlite3.Connection, *, dry_run: bool = False, limit: int | None = None,
        client: Callable[[], httpx.Client] = _client) -> Report:
    report = Report()
    for row in candidates(conn)[:limit]:
        result = check(row.posting.source_url, client=client)
        report.checked += 1
        was_closed = closed_at_source(conn, row.application.id)
        if result.state == "closed":
            report.closed.append((row, result))
            if not dry_run and was_closed != result.reason:
                db.add_event(conn, row.application.id, CLOSED_EVENT, result.reason)
        elif result.state == "unreachable":
            report.unreachable.append((row, result))
        elif was_closed:
            report.reopened.append(row)
            if not dry_run:
                db.add_event(conn, row.application.id, OPEN_EVENT, "open again at the source")
    return report
