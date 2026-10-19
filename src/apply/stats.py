"""What the pipeline has taught you: where applications convert, and what you lack.

Two read-only views, both free:

- the funnel, by channel. The event log already records every transition, so
  "LinkedIn alerts get answered half as often as referrals" is a query, not a
  feeling. Stages are counted as reached, not as current status: an application
  that interviewed and was then rejected still counts as an interview.
- the gaps. Every named tool or method the postings you are pursuing ask for and
  your profile never mentions, tallied across postings. One posting's gap is
  noise; the same gap in eleven is a course to take.

Both ideas come from MadsLorentzen/ai-job-search (/html-report's funnel and
/upskill's gap heatmap), done here deterministically from apply.db.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
import statistics
from collections import defaultdict
from dataclasses import dataclass, field

from . import ats
from .models import CLOSED

#: Event kinds that mean the employer did something after you submitted.
RESPONSE = {"ack", "oa_received", "interview", "offer", "reject"}
INTERVIEW = {"interview", "offer"}


@dataclass(slots=True)
class Funnel:
    channel: str
    submitted: int = 0
    responded: int = 0
    interviewed: int = 0
    offers: int = 0
    days_to_response: list[int] = field(default_factory=list)

    @property
    def median_days(self) -> float | None:
        return statistics.median(self.days_to_response) if self.days_to_response else None


def _ts(value: str) -> _dt.datetime:
    return _dt.datetime.fromisoformat(value.replace("Z", "+00:00").split("+")[0])


def funnel(conn: sqlite3.Connection) -> list[Funnel]:
    """One row per channel that has a submitted application, plus 'all' last."""
    apps = conn.execute(
        "SELECT a.id, a.submitted_at, COALESCE(NULLIF(p.source, ''), 'manual') AS channel "
        "FROM application a JOIN posting p ON p.id = a.posting_id "
        "WHERE a.submitted_at IS NOT NULL"
    ).fetchall()
    kinds: dict[int, list[tuple[str, str]]] = defaultdict(list)
    for e in conn.execute("SELECT application_id, kind, occurred_at FROM event "
                          "ORDER BY occurred_at, id"):
        kinds[e["application_id"]].append((e["kind"], e["occurred_at"]))

    rows: dict[str, Funnel] = {}
    total = Funnel("all")
    for a in apps:
        f = rows.setdefault(a["channel"], Funnel(a["channel"]))
        seen = kinds.get(a["id"], [])
        responses = [at for kind, at in seen if kind in RESPONSE]
        for target in (f, total):
            target.submitted += 1
            if responses:
                target.responded += 1
                days = (_ts(responses[0]) - _ts(a["submitted_at"])).days
                target.days_to_response.append(max(days, 0))
            if any(kind in INTERVIEW for kind, _ in seen):
                target.interviewed += 1
            if any(kind == "offer" for kind, _ in seen):
                target.offers += 1
    ordered = sorted(rows.values(), key=lambda f: -f.submitted)
    return [*ordered, total] if ordered else []


@dataclass(slots=True)
class Gap:
    term: str
    postings: list[str] = field(default_factory=list)   # "Company — Role"
    firms: list[str] = field(default_factory=list)      # one entry per posting


def gaps(conn: sqlite3.Connection, sources: str, *, include_maybe: bool = True) -> list[Gap]:
    """Named skills the live postings ask for that appear nowhere in your sources.

    Live means: not rejected by the scorer, and not rejected or withdrawn as an
    application. Sorted by how many postings ask, most first.
    """
    verdicts = ("pursue", "maybe") if include_maybe else ("pursue",)
    rows = conn.execute(
        "SELECT p.company, p.role, p.jd_raw, p.score_verdict, a.status "
        "FROM posting p LEFT JOIN application a ON a.posting_id = p.id"
    ).fetchall()
    tally: dict[str, Gap] = {}
    for r in rows:
        if r["status"] in CLOSED:
            continue
        # A hand-added posting has no verdict; it was added because it matters.
        if r["score_verdict"] is not None and r["score_verdict"] not in verdicts:
            continue
        for term in ats.gaps(r["jd_raw"] or "", sources):
            gap = tally.setdefault(term, Gap(term))
            gap.postings.append(f"{r['company']} — {r['role']}")
            gap.firms.append(r["company"])
    return sorted(tally.values(), key=lambda g: (-len(g.postings), g.term))
