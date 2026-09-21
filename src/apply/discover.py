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
import re
from collections import Counter
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


_SUFFIXES = re.compile(
    r"\b(inc|incorporated|llc|l\.l\.c|lp|l\.p|llp|ltd|limited|plc|corp|corporation|"
    r"co|company|group|holdings|the|& co)\b\.?", re.I)


def employer_key(name: str) -> str:
    """Punctuation-, case- and suffix-insensitive: "J.P. Morgan" and "JPMorgan"
    are the same key, and so are "BlackRock, Inc." and "BlackRock"."""
    text = re.sub(r"^jobs via\s+", "", name or "", flags=re.I)
    text = _SUFFIXES.sub(" ", text)
    return re.sub(r"[^a-z0-9]", "", text.lower())


class Aliases:
    """Map any spelling of a registry employer back to its registry entry.

    A registry entry may list `aliases:` for spellings that differ in more than
    punctuation — "JPMorgan Chase & Co." for "JPMorgan". A registry name of six
    or more characters also matches as a prefix, so "BlackRock Financial
    Management" finds "BlackRock"; shorter names match exactly only, so "DRW"
    cannot swallow "DRW Holdings Trust Company" by accident.
    """

    def __init__(self, employers: list[dict]):
        self.exact: dict[str, dict] = {}
        self.prefix: list[tuple[str, dict]] = []
        for entry in employers:
            for spelling in [entry["name"], *(entry.get("aliases") or [])]:
                key = employer_key(spelling)
                if key:
                    self.exact.setdefault(key, entry)
                    if len(key) >= 6:
                        self.prefix.append((key, entry))
        self.prefix.sort(key=lambda pair: -len(pair[0]))   # longest first

    def find(self, name: str) -> dict | None:
        key = employer_key(name)
        if not key:
            return None
        if key in self.exact:
            return self.exact[key]
        for prefix, entry in self.prefix:
            if key.startswith(prefix):
                return entry
        return None

    def adopt(self, posting: RawPosting) -> bool:
        """Rewrite a posting's employer to the registry's name, priority and
        tracks. Returns whether it matched. Matching on the canonical name is
        what makes a LinkedIn copy and the firm's own-board copy fingerprint the
        same, and collapse to one posting."""
        entry = self.find(posting.employer)
        if entry is None:
            return False
        posting.raw = {**posting.raw, "listed_as": posting.employer}
        posting.employer = entry["name"]
        posting.employer_priority = int(entry.get("priority", 3))
        posting.employer_tracks = tuple(entry.get("tracks") or ())
        return True


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
    #: Employers that surfaced in alert mail and are not in the registry yet —
    #: each one a firm whose full descriptions `apply resolve` could unlock.
    new_employers: Counter = field(default_factory=Counter)
    #: Job mail that parsed to nothing: the canary for a changed email layout.
    unparsed: list[str] = field(default_factory=list)
    skipped_old: int = 0

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
    #
    # The budget is spent only on postings that actually need a request, not on
    # the top N overall: Greenhouse arrives hydrated, so a naive top-N loop
    # burns its whole allowance skipping Greenhouse rows and never reaches the
    # Workday ones — which are exactly the rows whose deadline is only visible
    # after hydration.
    survivors.sort(key=lambda pair: -pair[1].value)
    needs_body = [pair for pair in survivors if not pair[0].hydrated]
    for posting, _ in needs_body[:hydrate_limit]:
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


#: The placeholder a title-only posting carries until `apply describe` replaces it.
_NO_DESCRIPTION = (
    "(description not retrieved — this came from an alert email, which carries "
    "only the title. Open the link above, copy the whole posting, then run: "
    "apply describe <slug> --clipboard)"
)


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
            jd_raw=header + (posting.description or _NO_DESCRIPTION),
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


# ------------------------------------------------------------- alert mail


@dataclass(slots=True)
class Message:
    """One alert email, however it was fetched."""

    subject: str
    body: str
    received: _dt.date
    sender: str = ""
    id: str = ""
    url: str | None = None

    @classmethod
    def from_dict(cls, raw: dict) -> "Message":
        received = raw.get("received") or raw.get("date") or ""
        if isinstance(received, str) and received:
            received = _dt.date.fromisoformat(received[:10])
        return cls(
            subject=raw.get("subject", ""),
            body=raw.get("body") or raw.get("plaintextBody") or "",
            received=received or _dt.date.today(),
            sender=raw.get("sender", ""),
            id=str(raw.get("id", "")),
            url=raw.get("url"),
        )


def ingest_alerts(
    conn,
    messages: list[Message],
    *,
    preferences: dict | None = None,
    dry_run: bool = False,
    employers: list[dict] | None = None,
    max_age_days: int | None = None,
) -> Result:
    """Turn job-alert emails — Handshake or LinkedIn — into postings, through the
    same gate as everything else.

    Alerts carry no description, so nothing that arrives this way can reach
    `pursue` on the strength of a title, which is the intended outcome: it is
    filed for a human to open, not fed to a letter writer. `apply describe`
    attaches the full text once you have read it.
    """
    from .sources.alerts import is_job_email, parse_alert, source_of

    preferences = preferences or {}
    aliases = Aliases(employers if employers is not None else load_employers())
    result = Result()
    today = _dt.date.today()

    raw: list[RawPosting] = []
    for message in messages:
        if not is_job_email(message.subject, message.sender, message.body):
            continue
        if max_age_days is not None and (today - message.received).days > max_age_days:
            result.skipped_old += 1     # an old alert lists roles that have closed
            continue
        result.fetched += 1
        found = parse_alert(message.subject, message.body, message.received,
                            url=message.url, sender=message.sender)
        if not found and source_of(message.sender, message.body) == "linkedin":
            result.unparsed.append(message.subject or message.id or "(no subject)")
        raw.extend(found)

    # Canonical names first, so the fingerprint agrees with the registry's copy.
    for posting in raw:
        aliases.adopt(posting)

    unique = dedupe(raw)
    result.unique = len(unique)

    for posting in unique:
        if db.fingerprint_exists(conn, posting.fingerprint):
            result.already_known += 1
            continue
        verdict = score_posting(posting, preferences)
        if verdict.verdict is Verdict.REJECT:
            result.rejected += 1
            result.rejections.append((posting, verdict))
            continue
        if verdict.verdict is Verdict.PURSUE:
            result.pursue.append((posting, verdict))
        else:
            result.maybe.append((posting, verdict))
        if aliases.find(posting.employer) is None and not posting.raw.get("reposted_by"):
            result.new_employers[posting.employer] += 1

    if not dry_run:
        for posting, verdict in result.worth_reading:
            slug = _store(conn, posting, verdict)
            if slug:
                result.created.append(slug)
    return result


def load_messages(path: Path) -> list[Message]:
    """Read an alert export. Accepts a bare list or {"messages": [...]}."""
    import json

    payload = json.loads(Path(path).read_text())
    rows = payload.get("messages") if isinstance(payload, dict) else payload
    return [Message.from_dict(row) for row in (rows or [])]


def fetch_imap(
    *,
    user: str,
    password: str,
    host: str = "imap.gmail.com",
    senders: tuple[str, ...] = ("joinhandshake.com", "jobalerts-noreply@linkedin.com",
                                "jobs-listings@linkedin.com"),
    days: int = 30,
    limit: int = 60,
) -> list[Message]:
    """Read alert mail over IMAP, for runs with no human and no connector.

    Gmail needs an app password here, not the account password. If VCU's
    Workspace forbids app passwords this raises, and the file-drop path is the
    fallback.
    """
    import email
    import imaplib
    from email.header import decode_header, make_header

    since = (_dt.date.today() - _dt.timedelta(days=days)).strftime("%d-%b-%Y")
    out: list[Message] = []
    connection = imaplib.IMAP4_SSL(host)
    try:
        connection.login(user, password)
        connection.select("INBOX", readonly=True)
        # IMAP's OR takes exactly two operands, so n senders nest n-1 deep.
        clause = f'FROM "{senders[-1]}"'
        for sender in reversed(senders[:-1]):
            clause = f'OR FROM "{sender}" {clause}'
        status, data = connection.search(None, f"(SINCE {since} {clause})")
        if status != "OK":
            return []
        ids = (data[0] or b"").split()[-limit:]
        for message_id in ids:
            status, raw = connection.fetch(message_id, "(RFC822)")
            if status != "OK" or not raw or not raw[0]:
                continue
            parsed = email.message_from_bytes(raw[0][1])
            subject = str(make_header(decode_header(parsed.get("Subject", ""))))
            received = _dt.date.today()
            if parsed.get("Date"):
                try:
                    received = email.utils.parsedate_to_datetime(parsed["Date"]).date()
                except (TypeError, ValueError):
                    pass
            body = _plain_text(parsed)
            out.append(Message(subject=subject, body=body, received=received,
                               sender=parsed.get("From", ""), id=message_id.decode()))
    finally:
        try:
            connection.logout()
        except Exception:                                 # noqa: BLE001
            pass
    return out


def _plain_text(parsed) -> str:
    """Prefer the text/plain part; fall back to stripping the HTML one."""
    from .sources.base import strip_html

    if not parsed.is_multipart():
        payload = parsed.get_payload(decode=True) or b""
        text = payload.decode(parsed.get_content_charset() or "utf-8", "replace")
        return text if parsed.get_content_type() == "text/plain" else strip_html(text)

    html = ""
    for part in parsed.walk():
        if part.get_content_type() == "text/plain":
            payload = part.get_payload(decode=True) or b""
            return payload.decode(part.get_content_charset() or "utf-8", "replace")
        if part.get_content_type() == "text/html" and not html:
            payload = part.get_payload(decode=True) or b""
            html = payload.decode(part.get_content_charset() or "utf-8", "replace")
    return strip_html(html)
