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
import time
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
    url: str | None = None   # a working link, when the stored one was broken


#: host -> [(tenant, site)], from the registry. Discovery used to store Workday
#: links with no site in them; the registry is what knows the site.
Sites = dict[str, list[tuple[str, str]]]

_sleep = time.sleep
#: The longest a Retry-After is honoured, in seconds.
MAX_WAIT = 30


def registry_sites() -> Sites:
    from .discover import load_employers

    sites: Sites = {}
    for entry in load_employers():
        if entry.get("ats") == "workday" and entry.get("host") and entry.get("site"):
            sites.setdefault(entry["host"].rstrip("/"), []).append(
                (str(entry.get("tenant") or ""), str(entry["site"])))
    return sites


def _patient(http: httpx.Client, url: str, **kwargs) -> httpx.Response:
    """One GET; a 429 is waited out (Retry-After, at most MAX_WAIT) and asked once more."""
    response = http.get(url, **kwargs)
    if response.status_code == 429:
        try:
            wait = float(response.headers.get("Retry-After", "5"))
        except ValueError:
            wait = 5.0
        _sleep(min(max(wait, 1.0), MAX_WAIT))
        response = http.get(url, **kwargs)
    return response


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


def _siteless(http: httpx.Client, url: str, sites: Sites) -> Result:
    """A Workday link with no site: try each site the registry has for the host."""
    from .sources import ats

    host = httpx.URL(url).host or ""
    candidates = sites.get(host, [])
    if not candidates:
        return Result("unreachable", "Workday link has no site, and the registry has "
                                     "none for this host")
    verdicts = []
    for tenant, site in candidates:
        fixed = ats.repaired_workday_url(url, tenant or host.split(".")[0], site)
        state = ats.workday_posting_state(
            http, fixed, get=lambda u: _patient(http, u, headers={"Accept": "application/json"}))
        if state is None:
            continue
        if state[0] == "open":
            return Result("open", "", fixed)
        verdicts.append((state, fixed))
    if verdicts and all(s[0] == "closed" for s, _ in verdicts):
        (state, reason), fixed = verdicts[0]
        return Result(state, reason, fixed)
    return Result("unreachable", verdicts[0][0][1] if verdicts else "no Workday answer")


def check(url: str, *, client: Callable[[], httpx.Client] = _client,
          sites: Sites | None = None) -> Result:
    from .sources import ats

    try:
        with client() as http:
            # A Workday job page is a JavaScript shell that loads whether or not
            # the job exists. Ask the API it renders from instead.
            if ats.is_siteless_workday(url):
                return _siteless(http, url, sites if sites is not None else registry_sites())
            workday = ats.workday_posting_state(
                http, url, get=lambda u: _patient(http, u, headers={"Accept": "application/json"}))
            if workday is not None:
                return Result(*workday)
            response = _patient(http, url)
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
    repaired: list[Row] = field(default_factory=list)


def candidates(conn: sqlite3.Connection) -> list[Row]:
    from .digest import in_pipeline

    return [r for r in db.rows(conn, SWEPT)
            if in_pipeline(r) and (r.posting.source_url or "").startswith(("http://", "https://"))]


def run(conn: sqlite3.Connection, *, dry_run: bool = False, limit: int | None = None,
        client: Callable[[], httpx.Client] = _client) -> Report:
    report = Report()
    sites = registry_sites()
    for row in candidates(conn)[:limit]:
        result = check(row.posting.source_url, client=client, sites=sites)
        report.checked += 1
        if result.url and result.url != row.posting.source_url:
            report.repaired.append(row)
            if not dry_run:
                row.posting.source_url = result.url
                db.update_posting(conn, row.posting)
                db.add_event(conn, row.application.id, "note",
                             f"link repaired: the stored Workday link had no site ({result.url})")
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
