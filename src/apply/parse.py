"""Raw job-description text -> a structured Posting.

Deterministic extraction first; an optional LLM pass only fills the fields regex
could not. Two rules the rest of the system leans on:

  * jd_raw is kept verbatim, always. Nothing in here discards source text.
  * A deadline is never guessed. If the year is missing or no date follows a
    deadline cue, the field stays None and the reason lands in `notes`, so the
    dashboard can say "verify manually" instead of quietly inventing a date.
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field

from .classify import Classification, classify
from .models import Posting, slugify

# --------------------------------------------------------------------- dates

_MONTH_NAMES = {
    m.lower(): i
    for i, m in enumerate(
        ["January", "February", "March", "April", "May", "June", "July",
         "August", "September", "October", "November", "December"], start=1)
}
_MONTH_NAMES.update({m[:3]: i for m, i in list(_MONTH_NAMES.items())})
_MONTH_ALT = "|".join(sorted(_MONTH_NAMES, key=len, reverse=True))

_DATE_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(rf"\b({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?,?\s+(\d{{4}})\b", re.I), "mdy"),
    (re.compile(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH_ALT})\.?,?\s+(\d{{4}})\b", re.I), "dmy"),
    (re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b"), "iso"),
    (re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b"), "slash"),
]

#: A date cue with no year attached — worth telling the owner about, never worth guessing.
_YEARLESS = re.compile(rf"\b({_MONTH_ALT})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b(?!,?\s*\d{{4}})", re.I)


@dataclass(slots=True)
class FoundDate:
    date: _dt.date
    start: int
    end: int
    text: str


def find_dates(text: str) -> list[FoundDate]:
    out: list[FoundDate] = []
    seen: set[tuple[int, int]] = set()
    for pattern, kind in _DATE_PATTERNS:
        for m in pattern.finditer(text):
            if (m.start(), m.end()) in seen:
                continue
            try:
                d = _build_date(kind, m.groups())
            except (ValueError, KeyError):
                continue
            if d is None:
                continue
            seen.add((m.start(), m.end()))
            out.append(FoundDate(d, m.start(), m.end(), m.group(0)))
    return sorted(out, key=lambda f: f.start)


def _build_date(kind: str, groups: tuple) -> _dt.date | None:
    if kind == "mdy":
        month = _MONTH_NAMES[groups[0].lower()]
        return _dt.date(int(groups[2]), month, int(groups[1]))
    if kind == "dmy":
        month = _MONTH_NAMES[groups[1].lower()]
        return _dt.date(int(groups[2]), month, int(groups[0]))
    if kind == "iso":
        return _dt.date(int(groups[0]), int(groups[1]), int(groups[2]))
    if kind == "slash":
        month, day, year = int(groups[0]), int(groups[1]), int(groups[2])
        if year < 100:
            year += 2000
        if month > 12:  # day-first, e.g. 14/10/2026
            month, day = day, month
        return _dt.date(year, month, day)
    return None


#: (cue, weight). A specific cue beats a bare "deadline" mentioned in passing.
_DEADLINE_CUES: list[tuple[str, int]] = [
    ("application deadline", 5), ("applications close", 5), ("applications are due", 5),
    ("apply by", 5), ("apply before", 5), ("last day to apply", 5),
    ("priority deadline", 5), ("closing date", 5), ("submit your application by", 5),
    ("accepting applications until", 4), ("open until", 3), ("applications due", 5),
    ("submit by", 4), ("due by", 4), ("closes on", 4), ("deadline", 3),
    ("must be received by", 4), ("review of applications begins", 3),
]

#: Cues that mark a date as something other than a deadline.
_NOT_DEADLINE = re.compile(
    r"\b(start date|starts?|begins?|beginning|orientation|posted|posting date|"
    r"expected start|program (?:begins|starts)|graduat|class of|founded|since)\b",
    re.I,
)


def find_deadline(text: str) -> tuple[_dt.date | None, list[str]]:
    """Return (deadline, notes). Notes explain a None so the owner can act on it."""
    notes: list[str] = []
    dates = find_dates(text)
    lowered = text.lower()
    best: tuple[int, int, _dt.date] | None = None  # (weight, -position, date)

    for cue, weight in _DEADLINE_CUES:
        for m in re.finditer(re.escape(cue), lowered):
            window_start, window_end = m.end(), m.end() + 120
            context = text[max(0, m.start() - 60):window_end]
            if _NOT_DEADLINE.search(context) and weight < 5:
                continue
            for fd in dates:
                if window_start <= fd.start <= window_end:
                    candidate = (weight, -fd.start, fd.date)
                    if best is None or candidate[:2] > best[:2]:
                        best = candidate
                    break
            else:
                # Cue with no usable date after it. Is there a year-less date?
                tail = text[window_start:window_end]
                ym = _YEARLESS.search(tail)
                if ym:
                    notes.append(
                        f'found "{cue} … {ym.group(0)}" with no year — set the '
                        f"deadline manually; the system will not guess one"
                    )

    if best is None:
        if not notes:
            notes.append("no application deadline stated in the posting")
        return None, notes
    return best[2], notes


# ---------------------------------------------------------------------- comp

_COMP_PATTERNS = [
    re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?\s?[-–—to]{1,3}\s?\$?\s?\d[\d,]*(?:\.\d+)?\s?(?:k\b|/\s?(?:hr|hour)|per\s+hour|/\s?yr|per\s+year)", re.I),
    re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?\s?(?:k\b|/\s?(?:hr|hour)|per\s+hour|/\s?yr|per\s+year)", re.I),
    re.compile(r"\$\s?\d[\d,]{4,}(?:\.\d+)?(?:\s?[-–—]\s?\$?\s?\d[\d,]{4,})?", re.I),
]


def find_comp(text: str) -> str | None:
    for pattern in _COMP_PATTERNS:
        m = pattern.search(text)
        if m:
            return re.sub(r"\s+", " ", m.group(0)).strip()
    return None


# ------------------------------------------------------------------ location

_LABEL = r"(?:^|\n)\s*{}\s*[:\-–]\s*(.+)"
_STATES = (
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO "
    "MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC"
).split()
_STATE_NAMES = (
    "Alabama Alaska Arizona Arkansas California Colorado Connecticut Delaware Florida "
    "Georgia Hawaii Idaho Illinois Indiana Iowa Kansas Kentucky Louisiana Maine Maryland "
    "Massachusetts Michigan Minnesota Mississippi Missouri Montana Nebraska Nevada "
    "Ohio Oklahoma Oregon Pennsylvania Tennessee Texas Utah Vermont Virginia Washington "
    "Wisconsin Wyoming"
).split() + ["New Hampshire", "New Jersey", "New Mexico", "New York", "North Carolina",
             "North Dakota", "Rhode Island", "South Carolina", "South Dakota",
             "West Virginia", "District of Columbia"]

_STATE_ALT = "|".join(_STATES + sorted(_STATE_NAMES, key=len, reverse=True))
_CITY_STATE = re.compile(
    rf"\b([A-Z][A-Za-z.'-]+(?:[^\S\n]+[A-Z][A-Za-z.'-]+){{0,2}}),[^\S\n]*({_STATE_ALT})\b")


def _labelled(text: str, *labels: str) -> str | None:
    for label in labels:
        m = re.search(_LABEL.format(label), text, re.I)
        if m:
            # Keep a trailing period: "Smith & Co." and "Acme Inc." are names,
            # not sentences.
            value = m.group(1).strip().strip(",;")
            if value and len(value) < 120:
                return value
    return None


def find_location(text: str) -> str | None:
    value = _labelled(text, "location", "locations", "office", "work location")
    if value:
        return value
    if re.search(r"\bfully remote\b|\bremote\b", text, re.I):
        remote = "Remote"
        m = _CITY_STATE.search(text)
        return f"{m.group(1)}, {m.group(2)} / {remote}" if m else remote
    m = _CITY_STATE.search(text)
    return f"{m.group(1)}, {m.group(2)}" if m else None


# ---------------------------------------------------------- company and role

_ROLE_WORDS = re.compile(
    r"\b(analyst|intern|internship|associate|engineer|developer|manager|program|"
    r"trader|trading|researcher|research|summer|full[- ]time|coordinator|specialist|"
    r"consultant|fellow|apprentice|rotational|scholar|assistant|officer|"
    r"scientist|quant|strategist|accountant|auditor|actuary|banker|trainee|"
    r"graduate|advisor|adviser|architect|controller)\b", re.I)
_CORP_WORDS = re.compile(
    r"\b(inc|llc|l\.l\.c|lp|l\.p|ltd|plc|corp|corporation|company|co|&\s*co|"
    r"capital|partners|group|management|advisors|advisers|bank|holdings|"
    r"associates|securities|investments?|university|foundation|trust)\b\.?", re.I)
_SPLITTERS = re.compile(r"\s+[|•·—–]\s+|\s+-\s+")
_NOISE = re.compile(r"^(job|posting|position|apply|share|save|about the (job|role))\b", re.I)
#: Lines that are a labelled field, a date, or a sentence are never a bare
#: company or role heading. _labelled() has already had its look at them.
_LABEL_LINE = re.compile(
    r"^(company|employer|organization|organisation|firm|job title|position title|"
    r"title|position|role|job|location|locations|office|work location|pay|salary|"
    r"compensation|deadline|application deadline|posted|posted on|date posted|"
    r"applications?)\b\s*[:\-–]", re.I)

_JOB_BOARD_HOSTS = {
    "myworkdayjobs.com": None, "workday.com": None, "greenhouse.io": None,
    "lever.co": None, "ashbyhq.com": None, "smartrecruiters.com": None,
    "icims.com": None, "taleo.net": None, "linkedin.com": None,
}


def find_url(text: str) -> str | None:
    m = re.search(r"https?://[^\s<>\"')\]]+", text)
    return m.group(0).rstrip(".,;") if m else None


def _first_lines(text: str, n: int = 8) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or _NOISE.match(line) or len(line) > 140:
            continue
        if _LABEL_LINE.match(line) or find_dates(line):
            continue
        lines.append(line)
        if len(lines) >= n:
            break
    return lines


#: "Hartford, CT", "Hartford, Connecticut", "Remote" — a place, not an employer.
_LOOKS_LOCATION = re.compile(
    rf"^(remote|hybrid|on-?site)\b|,\s*(?:{_STATE_ALT})\.?$", re.I)

_MINOR_WORDS = {"of", "and", "the", "for", "at", "in", "a", "an", "&", "de", "la"}


def _title_ish(line: str) -> bool:
    """Every word capitalised, ignoring connectives.

    str.istitle() is no help here: it says False for BlackRock, JPMorgan and
    eBay, and False again for a board that shouts — QUILLON ASSET MANAGEMENT.
    Firms capitalise their names however they like, and all of it has to parse.
    """
    words = line.split()
    if not words:
        return False
    return all(
        w[0].isupper()
        or w[0].isdigit()
        or any(c.isupper() for c in w[1:])          # eBay, iRobot
        or w.lower().strip(".,") in _MINOR_WORDS
        for w in words
    )


def _heading_like(line: str, max_words: int = 12) -> bool:
    """A heading is short, unpunctuated, and not a sentence."""
    if len(line.split()) > max_words:
        return False
    if line.rstrip().endswith((".", "!", "?", ":", ";")):
        return False
    return line.count(".") <= 1


def find_company_and_role(text: str) -> tuple[str | None, str | None, list[str]]:
    """Returns (company, role, notes). Either may be None; the caller supplies it."""
    notes: list[str] = []
    company = _labelled(text, "company", "employer", "organization", "organisation", "firm")
    role = _labelled(text, "job title", "position title", "title", "position", "role", "job")

    if company and role:
        return company, role, notes

    lines = _first_lines(text)

    # "Company — Role" or "Role | Company" on one line.
    for line in lines[:3]:
        parts = [p.strip() for p in _SPLITTERS.split(line) if p.strip()]
        if len(parts) == 2:
            a, b = parts
            a_role, b_role = bool(_ROLE_WORDS.search(a)), bool(_ROLE_WORDS.search(b))
            if a_role != b_role:
                role = role or (a if a_role else b)
                company = company or (b if a_role else a)
                return company, role, notes

    # "<Role> at <Company>"
    for line in lines[:4]:
        m = re.match(r"^(.{3,80}?)\s+at\s+(.{2,60})$", line)
        if m and _ROLE_WORDS.search(m.group(1)):
            role = role or m.group(1).strip()
            company = company or m.group(2).strip(" .")
            return company, role, notes

    # Otherwise: first role-looking line is the role, first company-looking line
    # that is not the role is the company.
    if role is None:
        for line in lines:
            if _ROLE_WORDS.search(line) and _heading_like(line):
                role = line
                break
    if company is None:
        for line in lines:
            if line == role or not _heading_like(line, max_words=6):
                continue
            if _LOOKS_LOCATION.search(line):
                continue
            if _CORP_WORDS.search(line) or _title_ish(line):
                company = line.strip(" .,")
                break

    if company is None:
        notes.append("could not read the company from the text — supply it with --company")
    if role is None:
        notes.append("could not read the role from the text — supply it with --role")
    return company, role, notes


# ------------------------------------------------------------------- result


@dataclass(slots=True)
class Parsed:
    jd_raw: str
    company: str | None = None
    role: str | None = None
    location: str | None = None
    comp: str | None = None
    deadline: _dt.date | None = None
    posted_at: _dt.date | None = None
    source_url: str | None = None
    source: str | None = None
    classification: Classification | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return bool(self.company and self.role)

    def to_posting(self, slug: str | None = None, year: int | None = None) -> Posting:
        if not self.complete:
            raise ValueError("company and role are required before creating a posting")
        track = self.classification.track.value if self.classification else "corporate"
        year = year or (self.deadline.year if self.deadline else _dt.date.today().year)
        return Posting(
            slug=slug or slugify(self.company, self.role, year),
            company=self.company,
            role=self.role,
            track=track,
            jd_raw=self.jd_raw,
            source=self.source,
            source_url=self.source_url,
            location=self.location,
            comp=self.comp,
            deadline=self.deadline,
            posted_at=self.posted_at,
        )


def parse(text: str, *, source: str | None = None, source_url: str | None = None) -> Parsed:
    """Deterministic pass. Never mutates or trims the source text."""
    company, role, notes = find_company_and_role(text)
    deadline, deadline_notes = find_deadline(text)
    posted = _labelled(text, "posted", "posted on", "date posted")
    posted_at = None
    if posted:
        found = find_dates(posted)
        posted_at = found[0].date if found else None

    return Parsed(
        jd_raw=text,
        company=company,
        role=role,
        location=find_location(text),
        comp=find_comp(text),
        deadline=deadline,
        posted_at=posted_at,
        source_url=source_url or find_url(text),
        source=source,
        classification=classify(text),
        notes=notes + deadline_notes,
    )
