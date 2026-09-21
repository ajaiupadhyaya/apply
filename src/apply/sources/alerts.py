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
HANDSHAKE_SENDERS = (
    "joinhandshake.com",
    "notifications.joinhandshake.com",
    "g.joinhandshake.com",
)

#: LinkedIn sends a great deal of mail; only these addresses carry job cards.
#: jobalerts-noreply is a saved-search alert, jobs-listings the "jobs you might
#: be interested in" digest. Both use the same card layout. Connection
#: suggestions (messages-noreply) and "searches included you"
#: (notifications-noreply) are not postings and are ignored.
LINKEDIN_JOB_SENDERS = (
    "jobalerts-noreply@linkedin.com",
    "jobs-listings@linkedin.com",
    "jobs-noreply@linkedin.com",
)

#: Kept for callers that only needed "is this Handshake".
SENDERS = HANDSHAKE_SENDERS


def source_of(sender: str = "", body: str = "") -> str | None:
    """"handshake", "linkedin", or None for mail this module does not read."""
    sender = (sender or "").lower()
    if any(s in sender for s in HANDSHAKE_SENDERS):
        return "handshake"
    if any(s in sender for s in LINKEDIN_JOB_SENDERS):
        return "linkedin"
    # A sender address can change; a LinkedIn job card cannot look like
    # anything else. Recognise the body if the address is new.
    if "linkedin.com" in sender and _LI_VIEW.search(body or ""):
        return "linkedin"
    return None

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


def is_job_email(subject: str, sender: str = "", body: str = "") -> bool:
    """Whether this message is worth parsing at all."""
    subject = (subject or "").strip()
    source = source_of(sender, body) if sender else "handshake"
    if source is None:
        return False
    if source == "linkedin":
        return True                     # the sender list is already job-only
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
    sender: str = "",
) -> list[RawPosting]:
    """Every posting in one alert email, whichever service sent it."""
    if source_of(sender, body) == "linkedin":
        return parse_linkedin(body, received)
    return parse_handshake(subject, body, received, url=url)


def parse_handshake(
    subject: str,
    body: str,
    received: _dt.date,
    *,
    url: str | None = None,
) -> list[RawPosting]:
    """Pull every posting out of one Handshake alert email.

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


# ----------------------------------------------------------------- LinkedIn
#
# Established against a real LinkedIn job email on 2026-09-21. A card is:
#
#     <title>
#     <company>
#     <location>
#     <zero or more insight lines>
#     View job: https://www.linkedin.com/comm/jobs/view/<id>/?<tracking>
#
# with cards separated by a rule of dashes. Parsing anchors on the "View job"
# line and reads the card upward from it, so LinkedIn adding or dropping an
# insight line does not move the title, company or location.
#
# The tracking query string carries an otpToken — a one-time sign-in token —
# so every URL is reduced to its bare /jobs/view/<id>/ form before it is stored
# anywhere, and nothing with a token in it reaches the repo or the database.

_LI_VIEW = re.compile(r"View job:\s*(https?://\S+)", re.I)
_LI_JOB_ID = re.compile(r"/jobs/view/(\d+)")

#: Lines LinkedIn adds to a card that describe the listing, not the job.
_LI_INSIGHT = re.compile(
    r"^(this company is actively hiring|actively recruiting|be (the )?first( of [\d,]+)? to apply"
    r"|be an early applicant|apply with resume.*|easy apply|promoted|recently posted"
    r"|reposted.*|viewed|new|top applicant.*|your profile matches.*|[\d,]+ applicants?"
    r"|[\d,]+ (connections?|school alumn\w*|company alumn\w*|alumni).*"
    r"|.*\b(work|works|worked) here$|fast[- ]growing|in your network)$",
    re.I,
)

#: A card whose "company" is a job board re-posting someone else's role.
_LI_REPOST = re.compile(r"^jobs via\s+(.+)$", re.I)


def clean_linkedin_url(url: str) -> tuple[str, str]:
    """(bare job URL, job id). Drops every tracking parameter, including the
    one-time sign-in token LinkedIn embeds in each link."""
    match = _LI_JOB_ID.search(url or "")
    if not match:
        return "", ""
    job_id = match.group(1)
    return f"https://www.linkedin.com/jobs/view/{job_id}/", job_id


def parse_linkedin(body: str, received: _dt.date) -> list[RawPosting]:
    """Every job card in one LinkedIn email."""
    if not body:
        return []
    lines = body.splitlines()
    out: list[RawPosting] = []
    seen: set[str] = set()

    for index, line in enumerate(lines):
        match = _LI_VIEW.search(line)
        if not match:
            continue
        url, job_id = clean_linkedin_url(match.group(1))
        if not job_id or job_id in seen:
            continue

        # Read the card upward from the View job line until a blank line or a rule.
        card: list[str] = []
        for above in reversed(lines[:index]):
            text = above.strip()
            if not text or set(text) <= set("-—_="):
                break
            card.append(text)
        card.reverse()

        content = [c for c in card if not _LI_INSIGHT.match(c)
                   and not c.lower().startswith("http")
                   and not c.lower().startswith("top job picks")]
        pay = next((c for c in content[3:] if c.startswith("$")), "")
        content = [c for c in content if not c.startswith("$")]
        if len(content) < 2:
            continue

        title, company = content[0], content[1]
        location = content[2] if len(content) > 2 else None
        reposted = _LI_REPOST.match(company)

        seen.add(job_id)
        out.append(RawPosting(
            employer=company,
            title=title,
            url=url,
            source="linkedin",
            external_id=job_id,
            location=location,
            description="",                    # the posting itself sits behind LinkedIn's login
            posted_at=received,
            employer_priority=3,
            raw={"via": "linkedin-alert", "pay": pay,
                 "reposted_by": reposted.group(1).strip() if reposted else None},
        ))
    return out
