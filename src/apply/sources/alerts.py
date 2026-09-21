"""Parsing job-alert emails.

Handshake will not be scraped, but Handshake sends mail, and its mail carries
the one thing the ATS registry cannot reach: the postings that exist only inside
Handshake. This module turns those emails into RawPostings.

It parses text, not a mailbox. The transport is somebody else's problem — IMAP
for an unattended run, a JSON drop when Claude does the fetching through a
connector — because the parsing is the part that is hard, and the part worth
testing. Both paths call `parse_alert`.

What the emails actually look like was established by reading two real ones on
2026-09-20; the fixtures in tests/fixtures/alerts/ are those two, lightly
redacted. Handshake will change the format eventually. When it does,
`is_job_email` will keep returning True and `parse_alert` will start returning
nothing, which is the failure mode to watch for.
"""

from __future__ import annotations

import datetime as _dt
import re

from .base import RawPosting

#: Handshake sends from two subdomains, and which one tells you nothing useful
#: about whether the mail contains jobs — the subject does.
SENDERS = (
    "joinhandshake.com",
    "notifications.joinhandshake.com",
    "g.joinhandshake.com",
)

#: Subjects that carry job listings.
JOB_SUBJECTS = [
    r"sees you as a top applicant",          # weekly round-up
    r"new matches for your saved search",
    r'^"?search on ',                        # a saved search, named by its date
    r"added to collections you follow",
    r"is about to close",                    # carries a deadline
    r"flexible jobs near you",
    r"jobs? (for|just for) you",
    r"weekly jobs round-?up",
    r"new jobs? (added|posted)",
]

#: Subjects that look like Handshake but carry no postings. Checked first,
#: because "Application sent to X — here's what's next" contains an "apply to
#: similar jobs" block that is not a listing you have not already seen.
NOT_JOB_SUBJECTS = [
    r"application (was )?sent",
    r"upcoming appointment",
    r"appointment (with|has|reminder)",
    r"you have a new notification",
    r"reactivation request",
    r"school registration",
    r"password", r"verify your", r"welcome to handshake",
    r"just messaged you",                    # a recruiter, not a posting
    r"your application (status|was viewed)",
    r"event (reminder|registration)",
]

_META = re.compile(
    r"""^
    (?:Promoted\s*[•·]\s*)?                  # some rows are sponsored
    (?:(?P<pay>\$[^•·]+?)\s*[•·]\s*)?        # "$100K/yr", "$20-30/hr"
    (?P<kind>Full-?Time|Part-?Time|Internship|Fellowship|Contract|Temporary|
        Volunteer|Apprenticeship|On\s+Campus\s+Student\s+Employment|Co-?op)
    \s*[•·]\s*
    (?P<location>.+?)
    \s*$""",
    re.I | re.X,
)

#: "Thu, Sep 24 12:59 am EDT" and the shapes either side of it. No year: the
#: email's own date supplies that.
_DUE = re.compile(
    r"(?:due|closes?|closing|deadline)[^\n]{0,40}?\n*\s*"
    r"(?:[A-Z][a-z]{2},?\s+)?"                       # optional weekday
    r"(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+"
    r"(?P<day>\d{1,2})"
    r"(?:\s*,?\s*(?P<year>20\d\d))?",
    re.I,
)

_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun",
     "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}

#: Lines that are chrome, not content.
_CHROME = re.compile(
    r"^(view more jobs|apply now|you got this|update your career interests"
    r"|see all jobs|view job|browse|handshake|unsubscribe|new jobs just for you"
    r"|last chance to apply|your weekly jobs round-?up|.*sent every week"
    r"|new matches for your saved search|.*salary|applications? for .* are due"
    r"|flexible work that fits your schedule|.*around classes.*)$", re.I)


def is_job_email(subject: str, sender: str = "") -> bool:
    """Whether this message is worth parsing at all."""
    subject = (subject or "").strip()
    if sender and not any(s in sender.lower() for s in SENDERS):
        return False
    lowered = subject.lower()
    if any(re.search(p, lowered) for p in NOT_JOB_SUBJECTS):
        return False
    return any(re.search(p, lowered) for p in JOB_SUBJECTS)


def _resolve_year(month: int, day: int, received: _dt.date) -> _dt.date | None:
    """A deadline in an alert has no year. The email's own date supplies it.

    This is not the parser guessing: a message sent on 20 September saying
    "due Sep 24" is unambiguous. The chosen date is the next occurrence at or
    after the send date, which is the only reading that makes sense for a
    deadline.
    """
    for year in (received.year, received.year + 1):
        try:
            candidate = _dt.date(year, month, day)
        except ValueError:
            return None
        # A day or two of slack: Handshake sends "last chance" mail the morning
        # of the deadline, and timezones make that look like yesterday.
        if candidate >= received - _dt.timedelta(days=2):
            return candidate
    return None


def find_deadline(body: str, received: _dt.date) -> _dt.date | None:
    match = _DUE.search(body or "")
    if not match:
        return None
    month = _MONTHS.get(match.group("month")[:3].lower())
    if not month:
        return None
    if match.group("year"):
        try:
            return _dt.date(int(match.group("year")), month, int(match.group("day")))
        except ValueError:
            return None
    return _resolve_year(month, int(match.group("day")), received)


def _clean_location(text: str) -> str:
    """"New York City, NY +2 (Onsite)" -> "New York City, NY"."""
    text = re.sub(r"\s*\((?:onsite|hybrid|remote)\)\s*$", "", text, flags=re.I)
    text = re.sub(r"\s*\+\d+\s*$", "", text)
    return text.strip(" ,")


def parse_alert(
    subject: str,
    body: str,
    received: _dt.date,
    *,
    url: str | None = None,
) -> list[RawPosting]:
    """Pull every posting out of one alert email.

    The layout is three blocks: the employer and role on consecutive lines, a
    blank line, then a metadata line of pay, job type and location separated by
    bullets. Everything else is chrome.
    """
    if not body:
        return []
    deadline = find_deadline(body, received)
    blocks = [b.strip() for b in re.split(r"\n\s*\n", body) if b.strip()]

    out: list[RawPosting] = []
    for index, block in enumerate(blocks):
        meta = _META.match(block.strip())
        if not meta or index == 0:
            continue
        lines = [l.strip() for l in blocks[index - 1].splitlines() if l.strip()]
        lines = [l for l in lines if not _CHROME.match(l)]
        if len(lines) < 2:
            continue
        employer, role = lines[0], " ".join(lines[1:])
        if not employer or not role or len(role) > 160:
            continue

        out.append(RawPosting(
            employer=employer,
            title=role,
            url=url or "",
            source="alert",
            location=_clean_location(meta.group("location")),
            description="",                  # alerts carry no description
            posted_at=received,
            # Only the "about to close" mail states one, and it applies to the
            # single posting it is about. A round-up's postings get nothing.
            deadline=deadline if len(blocks) < 12 else None,
            employer_priority=3,
            raw={"subject": subject, "pay": (meta.group("pay") or "").strip(),
                 "kind": meta.group("kind"), "via": "handshake-alert"},
        ))
    return out
