"""One unattended pass: discover, ingest, write, report.

This is the thing you start before you leave. It has to be safe to run with
nobody watching, which mostly means being clear about what it will never do:

  * it never moves an application past `generated` — `ready` and `submitted`
    still belong to the review and submit actions, and this module does not
    call them
  * it never regenerates something that already has documents, so running it
    twice in an hour costs nothing the second time
  * it never spends past the ledger's ceilings, and a refused call ends that
    step rather than the run
  * it stops entirely if data/HALT exists, before doing anything at all

One employer being down, one letter failing to compile, or the mailbox being
unreachable are all recorded and stepped over. A run that half-worked is more
useful than a run that raised.
"""

from __future__ import annotations

import datetime as _dt
import traceback
from dataclasses import dataclass, field
from pathlib import Path

from . import db, digest as digest_mod, discover, generate
from .budget import Budget, BudgetExceeded
from .llm import LLMUnavailable
from .models import Status
from .profile import Profile, data_dir

#: Drop a file here and the next run does nothing. The simplest possible brake,
#: and one that works when nothing else does.
HALT_FILE = "HALT"


@dataclass(slots=True)
class Step:
    name: str
    ok: bool = True
    detail: str = ""

    def __str__(self) -> str:
        return f"{'ok ' if self.ok else 'FAIL'} {self.name}: {self.detail}"


@dataclass(slots=True)
class RunReport:
    run_id: str
    started_at: _dt.datetime
    finished_at: _dt.datetime | None = None
    discovered: int = 0
    ingested: int = 0
    generated: list[str] = field(default_factory=list)
    generation_failed: list[tuple[str, str]] = field(default_factory=list)
    skipped_budget: int = 0
    usd: float = 0.0
    steps: list[Step] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    halted: bool = False

    @property
    def duration(self) -> float:
        end = self.finished_at or _dt.datetime.now()
        return (end - self.started_at).total_seconds()

    @property
    def quiet(self) -> bool:
        return not (self.discovered or self.ingested or self.generated)


def halted(directory: Path | None = None) -> Path | None:
    """The brake. Returns the halt file if it exists."""
    path = (directory or data_dir()) / HALT_FILE
    return path if path.exists() else None


def run(
    *,
    llm: str = "api",
    generate_limit: int | None = None,
    discover_postings: bool = True,
    ingest_mail: bool = True,
    hydrate: int = 60,
    dry_run: bool = False,
) -> RunReport:
    """The whole pass. Safe to call repeatedly."""
    started = _dt.datetime.now()
    report = RunReport(run_id=started.strftime("run-%Y%m%d-%H%M%S"), started_at=started)

    brake = halted()
    if brake:
        report.halted = True
        report.finished_at = _dt.datetime.now()
        report.steps.append(Step("halt", False, f"{brake} exists; nothing was done"))
        return report

    conn = db.connect()
    profile = Profile.load()
    preferences = profile.search_preferences
    budget = Budget(conn, caps=(profile.raw.get("budget") or {}), run_id=report.run_id)
    cap = generate_limit if generate_limit is not None else int(
        preferences.get("max_auto_per_day", 5))

    # 1 — the employer registry.
    if discover_postings:
        try:
            found = discover.run(conn, preferences=preferences,
                                 hydrate_limit=hydrate, dry_run=dry_run)
            report.discovered = len(found.created)
            report.errors += found.errors
            report.steps.append(Step(
                "discover", True,
                f"{found.fetched} fetched, {found.rejected} rejected, "
                f"{len(found.created)} filed"
                + (f", {found.deferred} deferred to the next run" if found.deferred else "")))
        except Exception as exc:                        # noqa: BLE001
            report.steps.append(Step("discover", False, f"{type(exc).__name__}: {exc}"))
            report.errors.append(traceback.format_exc(limit=2))

    # 2 — the alert mailbox. Optional, and its absence is not a failure.
    if ingest_mail:
        try:
            messages = _mail(profile)
            if messages is None:
                report.steps.append(Step("ingest", True, "no mailbox configured; skipped"))
            else:
                got = discover.ingest_alerts(conn, messages, preferences=preferences,
                                             dry_run=dry_run, max_age_days=21)
                report.ingested = len(got.created)
                detail = (f"{len(messages)} messages, {got.rejected} rejected, "
                          f"{len(got.created)} filed")
                if got.new_employers:
                    detail += f", {len(got.new_employers)} firms not in the registry"
                report.steps.append(Step("ingest", not got.unparsed, detail
                    + (f"; {len(got.unparsed)} LinkedIn email(s) parsed to nothing — "
                       f"layout may have changed" if got.unparsed else "")))
        except Exception as exc:                        # noqa: BLE001
            report.steps.append(Step("ingest", False, f"{type(exc).__name__}: {exc}"))

    # 3 — write documents for the postings that earned one.
    if cap > 0 and not dry_run:
        _write_documents(conn, profile, budget, report, llm=llm, cap=cap)

    report.usd = budget.run_to_date()
    report.finished_at = _dt.datetime.now()
    _record(conn, report)
    return report


def _mail(profile: Profile) -> list[discover.Message] | None:
    """Alert mail, if a transport is configured. None means 'not set up'."""
    import os

    # Same reason as the API key: launchd never reads ~/.zshrc, so the
    # environment variable is absent at 06:30. The Keychain is not.
    from .llm import _keychain_key

    password = os.environ.get("APPLY_IMAP_PASSWORD") or _keychain_key("APPLY_IMAP_PASSWORD")
    if password:
        return discover.fetch_imap(user=profile.email, password=password)
    drop = data_dir() / "alerts.json"
    if drop.exists():
        return discover.load_messages(drop)
    return None


def _needs_documents(row) -> bool:
    """Only postings that have earned a letter, and do not already have one."""
    if row.application.status != Status.DRAFT.value:
        return False                       # already generated, or further along
    if row.posting.score_verdict != "pursue":
        return False
    # An alert gives a title and nothing else. There is no letter to write from
    # that, and pretending otherwise is how a system starts inventing things.
    return len(row.posting.jd_raw or "") > 600


def _write_documents(conn, profile, budget, report, *, llm: str, cap: int) -> None:
    candidates = [r for r in db.rows(conn) if _needs_documents(r)]
    candidates.sort(key=lambda r: (
        r.days_left if r.days_left is not None else 9_999,
        -(r.posting.score or 0),
    ))

    for row in candidates[:cap]:
        slug = row.posting.slug
        try:
            # The writer checks and records every call against the ledger
            # itself, so a letter that needs a revision is paid for honestly.
            artifacts = generate.build(profile, row.posting, llm=llm, budget=budget)
        except BudgetExceeded as exc:
            report.skipped_budget += 1
            report.steps.append(Step(f"write:{slug}", False, str(exc)))
            break                           # the ceiling will not move this run
        except LLMUnavailable as exc:
            report.steps.append(Step("write", False, str(exc).splitlines()[0]))
            break                           # no key, no network: nothing else will work
        except Exception as exc:                        # noqa: BLE001
            report.generation_failed.append((slug, f"{type(exc).__name__}: {exc}"))
            continue

        if artifacts.status == "prompt":
            continue                        # manual mode: PROMPT.md only, nothing to review

        if not artifacts.ok:
            why = getattr(artifacts.written, "reason", "") or "; ".join(artifacts.lint.errors)
            report.generation_failed.append((slug, why))
            db.add_event(conn, row.application.id, "note", f"not written: {why[:300]}")
            continue

        db.set_documents(
            conn, row.application.id,
            resume_variant=artifacts.resume_variant or None,
            letter_path=str(artifacts.letter_pdf) if artifacts.letter_pdf else None,
            resume_path=str(artifacts.resume_pdf) if artifacts.resume_pdf else None,
            fieldpack_path=str(artifacts.fieldpack) if artifacts.fieldpack else None,
        )
        # `generated` and no further. Reading it is still yours.
        db.transition(conn, row.application.id, Status.GENERATED, via="gen",
                      detail=f"written unattended by {report.run_id} "
                             f"({artifacts.status}, ${artifacts.written.cost:.2f})")
        report.generated.append(slug)


SCHEMA = """
CREATE TABLE IF NOT EXISTS run (
  id           INTEGER PRIMARY KEY,
  run_id       TEXT UNIQUE NOT NULL,
  started_at   TIMESTAMP,
  finished_at  TIMESTAMP,
  discovered   INTEGER DEFAULT 0,
  ingested     INTEGER DEFAULT 0,
  generated    INTEGER DEFAULT 0,
  usd          REAL DEFAULT 0,
  halted       INTEGER DEFAULT 0,
  summary      TEXT
);
"""


def _record(conn, report: RunReport) -> None:
    with conn:
        conn.executescript(SCHEMA)
        conn.execute(
            """INSERT OR REPLACE INTO run
               (run_id, started_at, finished_at, discovered, ingested, generated,
                usd, halted, summary)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (report.run_id,
             report.started_at.replace(microsecond=0).isoformat(sep=" "),
             (report.finished_at or _dt.datetime.now()).replace(microsecond=0).isoformat(sep=" "),
             report.discovered, report.ingested, len(report.generated),
             report.usd, int(report.halted),
             " | ".join(str(s) for s in report.steps)),
        )


def history(conn, limit: int = 10):
    with conn:
        conn.executescript(SCHEMA)
    return conn.execute(
        "SELECT * FROM run ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()


def summarise(conn, report: RunReport) -> str:
    """The morning read. Markdown, because it is also the notification body."""
    counts = digest_mod.headline(conn)
    d = digest_mod.build(conn)
    lines = [
        f"# apply — {report.started_at.strftime('%A %-d %B, %H:%M')}",
        "",
        f"{report.discovered} new from the registry · {report.ingested} from alerts · "
        f"{len(report.generated)} written · ${report.usd:.2f} spent · "
        f"{report.duration:.0f}s",
        "",
    ]
    if report.halted:
        lines += ["**Halted.** `data/HALT` exists, so nothing ran.", ""]
        return "\n".join(lines)

    if counts["awaiting_review"] or counts["ready"]:
        lines += ["## Needs you", ""]
        if counts["awaiting_review"]:
            lines.append(f"- {counts['awaiting_review']} awaiting review — `apply review <slug>`")
        if counts["ready"]:
            lines.append(f"- {counts['ready']} ready to submit")
        lines.append("")

    if d.overdue or d.deadlines:
        lines += ["## Deadlines", ""]
        for row in (d.overdue + d.deadlines)[:12]:
            left = row.days_left
            when = f"{-left}d ago" if left < 0 else f"{left}d"
            lines.append(f"- **{row.posting.deadline}** ({when}) {row.posting.company} — "
                         f"{row.posting.role}")
        lines.append("")

    if report.generated:
        lines += ["## Written overnight", ""]
        lines += [f"- `{slug}`" for slug in report.generated]
        lines.append("")

    if report.generation_failed:
        lines += ["## Could not be written", ""]
        lines += [f"- `{slug}` — {why}" for slug, why in report.generation_failed]
        lines.append("")

    if report.errors or any(not s.ok for s in report.steps):
        lines += ["## Problems", ""]
        lines += [f"- {s}" for s in report.steps if not s.ok]
        lines += [f"- {e.splitlines()[-1]}" for e in report.errors[:6]]
        lines.append("")

    lines += ["---", "", *(f"- {s}" for s in report.steps)]
    return "\n".join(lines)
