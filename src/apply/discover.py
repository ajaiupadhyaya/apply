"""One unattended pass: fetch, dedupe, score, hydrate the survivors, record.

The shape of this function is the whole cost argument. A Workday employer will
happily return four hundred openings; three of them are plausible. So:

    fetch      one request per employer, descriptions omitted where optional
    dedupe     by fingerprint, across sources and against what is already stored
    score      free, deterministic, on titles and locations
    hydrate    one request per posting, but only for the ones still standing
    re-score   now with the body, where the disqualifiers actually live
    record     pursue and maybe both become postings; reject never does

Nothing here writes a document, calls a model, or spends a cent. Discovery is
allowed to run as often as you like.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import db
from .models import Posting, slugify
from .score import Score, Verdict, score as score_posting
from .sources import ADAPTERS
from .sources.base import RawPosting, SourceError


def load_employers(path: Path | None = None) -> list[dict]:
    """The registry. Private by default: it is a list of where you are applying."""
    from .profile import data_dir

    path = path or (data_dir() / "employers.yaml")
    if not path.exists():
        return []
    payload = yaml.safe_load(path.read_text()) or {}
    employers = payload.get("employers") or []
    for entry in employers:
        entry.setdefault("priority", 3)
        entry.setdefault("enabled", True)
    return [e for e in employers if e.get("enabled")]


@dataclass(slots=True)
class Result:
    fetched: int = 0
    unique: int = 0
    already_known: int = 0
    rejected: int = 0
    hydrated: int = 0
    pursue: list[tuple[RawPosting, Score]] = field(default_factory=list)
    maybe: list[tuple[RawPosting, Score]] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    rejections: list[tuple[RawPosting, Score]] = field(default_factory=list)

    @property
    def worth_reading(self) -> list[tuple[RawPosting, Score]]:
        return sorted(self.pursue + self.maybe, key=lambda pair: -pair[1].value)


def fetch_all(employers: list[dict]) -> tuple[list[RawPosting], list[str]]:
    """Every employer, one request each. A source that fails is reported, not fatal."""
    postings: list[RawPosting] = []
    errors: list[str] = []
    for employer in employers:
        adapter = ADAPTERS.get(employer.get("ats", ""))
        if adapter is None:
            errors.append(f"{employer.get('name','?')}: unknown ats "
                          f"{employer.get('ats')!r} (expected one of {', '.join(ADAPTERS)})")
            continue
        try:
            postings.extend(adapter.fetch(employer))
        except SourceError as exc:
            errors.append(str(exc))
        except Exception as exc:                      # noqa: BLE001
            errors.append(f"{employer.get('name','?')}: {type(exc).__name__}: {exc}")
    return postings, errors


def dedupe(postings: list[RawPosting]) -> list[RawPosting]:
    """Collapse the same role seen twice. The richer copy wins."""
    best: dict[str, RawPosting] = {}
    for posting in postings:
        key = posting.fingerprint
        current = best.get(key)
        if current is None or len(posting.description) > len(current.description):
            best[key] = posting
    return list(best.values())


def run(
    conn,
    *,
    employers: list[dict] | None = None,
    preferences: dict | None = None,
    hydrate_limit: int = 60,
    dry_run: bool = False,
) -> Result:
    employers = employers if employers is not None else load_employers()
    preferences = preferences or {}
    result = Result()
    if not employers:
        result.errors.append(
            "no employers configured. Copy data/employers.example.yaml to "
            "data/employers.yaml and add the firms you are targeting."
        )
        return result

    by_name = {e["name"]: e for e in employers}

    raw, result.errors = fetch_all(employers)
    result.fetched = len(raw)
    unique = dedupe(raw)
    result.unique = len(unique)

    # Anything already in the database is not news.
    fresh = []
    for posting in unique:
        if db.fingerprint_exists(conn, posting.fingerprint):
            result.already_known += 1
        else:
            fresh.append(posting)

    # Free pass on titles and locations.
    survivors: list[tuple[RawPosting, Score]] = []
    for posting in fresh:
        verdict = score_posting(posting, preferences)
        if verdict.verdict is Verdict.REJECT:
            result.rejected += 1
            result.rejections.append((posting, verdict))
        else:
            survivors.append((posting, verdict))

    # Paid-in-requests pass, on the ones still standing, best first.
    survivors.sort(key=lambda pair: -pair[1].value)
    for posting, _ in survivors[:hydrate_limit]:
        if posting.hydrated:
            continue
        adapter = ADAPTERS.get(posting.source)
        config = by_name.get(posting.employer)
        if adapter is None or config is None:
            continue
        try:
            adapter.hydrate(posting, config)
            result.hydrated += 1
        except SourceError as exc:
            result.errors.append(str(exc))

    # Re-score with the body, which is where seniority and degree bars live.
    for posting, _ in survivors:
        verdict = score_posting(posting, preferences)
        if verdict.verdict is Verdict.REJECT:
            result.rejected += 1
            result.rejections.append((posting, verdict))
        elif verdict.verdict is Verdict.PURSUE:
            result.pursue.append((posting, verdict))
        else:
            result.maybe.append((posting, verdict))

    if not dry_run:
        for posting, verdict in result.worth_reading:
            slug = _store(conn, posting, verdict)
            if slug:
                result.created.append(slug)
    return result


def _store(conn, posting: RawPosting, verdict: Score) -> str | None:
    """Create the posting row. Returns the slug, or None if it already existed."""
    year = posting.deadline.year if posting.deadline else _dt.date.today().year
    base = slugify(posting.employer, posting.title, year)
    slug, suffix = base, 2
    while db.get_posting(conn, slug):
        slug = f"{base}-{suffix}"
        suffix += 1

    header = "\n".join([
        f"[discovered {_dt.date.today().isoformat()} via {posting.source}]",
        f"{posting.employer} — {posting.title}",
        f"Location: {posting.location or 'not stated'}",
        f"Source: {posting.url}",
        "",
    ])
    try:
        db.create_posting(conn, Posting(
            slug=slug,
            company=posting.employer,
            role=posting.title,
            track=verdict.track,
            jd_raw=header + (posting.description or "(description not retrieved)"),
            source=posting.source,
            source_url=posting.url,
            location=posting.location,
            deadline=posting.deadline,
            posted_at=posting.posted_at,
            priority=posting.employer_priority,
            fingerprint=posting.fingerprint,
            score=verdict.value,
            score_verdict=verdict.verdict.value,
            score_reasons="; ".join(verdict.reasons),
            discovered_at=_dt.datetime.now().replace(microsecond=0).isoformat(sep=" "),
        ))
    except Exception:                                 # noqa: BLE001 — unique index race
        return None
    return slug
