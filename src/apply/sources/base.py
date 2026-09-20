"""What every source returns, and what every source promises.

A source is anything that can hand back job postings without a credential and
without pretending to be a browser: a public ATS job-board API, a company's own
careers JSON, or the owner's own inbox. There is deliberately no scraper here.
Adding one would put the VCU-provisioned Handshake account at risk, and would
make every other source's data less trustworthy by association.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import re
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(slots=True)
class RawPosting:
    """One posting as a source found it, before scoring or classification."""

    employer: str
    title: str
    url: str
    source: str                       # greenhouse | lever | ashby | workday | email | page
    external_id: str = ""             # the ATS's own id, for deduplication
    location: str | None = None
    description: str = ""             # plain text; may be empty until hydrated
    posted_at: _dt.date | None = None
    deadline: _dt.date | None = None  # rarely present; never invented
    employer_priority: int = 3
    employer_tracks: tuple[str, ...] = ()
    raw: dict = field(default_factory=dict, repr=False)

    @property
    def fingerprint(self) -> str:
        """Stable identity across runs and across sources.

        The same role reached through Handshake's alert email and through the
        employer's own Greenhouse board must collapse to one posting, so the
        fingerprint deliberately ignores the URL and the source.
        """
        key = f"{_norm(self.employer)}|{_norm(self.title)}|{_city(self.location)}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    @property
    def hydrated(self) -> bool:
        """Whether the description is present. Listing endpoints often are not."""
        return len(self.description.strip()) > 200


#: Workday writes a location as "NY7 - 50 Hudson Yards, New York"; Greenhouse
#: writes "New York, New York, United States". The same desk, two strings, so
#: the fingerprint matches on the city rather than on the label.
_CITIES = [
    "new york", "jersey city", "stamford", "greenwich", "boston", "chicago",
    "san francisco", "philadelphia", "charlotte", "atlanta", "dallas", "houston",
    "los angeles", "miami", "austin", "seattle", "denver", "washington",
    "arlington", "richmond", "charlottesville", "mclean", "reston", "wilmington",
    "london", "hong kong", "singapore", "tokyo", "amsterdam", "mumbai",
    "bengaluru", "sydney", "toronto", "dublin", "shanghai", "remote",
]


def _city(location: str | None) -> str:
    if not location:
        return ""
    lowered = location.lower()
    for city in _CITIES:
        if city in lowered:
            return city
    return re.sub(r"[^a-z]+", " ", lowered).strip()


def _norm(text: str) -> str:
    """Aggressive normalisation — this is for matching, not for display."""
    text = text.lower()
    text = re.sub(r"\(.*?\)", " ", text)                 # "(AMRS)", "(Remote)"
    text = re.sub(r"\b(20\d\d|f?te?|i+)\b", " ", text)   # years, "FT", roman numerals
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(sorted(text.split()))                 # word order is not identity


class Source(Protocol):
    """Every adapter implements these two calls."""

    name: str

    def fetch(self, config: dict) -> list[RawPosting]:
        """List what the employer currently has open. Cheap; may omit descriptions."""

    def hydrate(self, posting: RawPosting, config: dict) -> RawPosting:
        """Fill in the description. One request per posting, so callers do this
        only for postings that already survived scoring."""


class SourceError(RuntimeError):
    """A source failed. Never fatal: one employer being down must not stop a run."""


def strip_html(html: str) -> str:
    """ATS descriptions come back as HTML fragments. We want the text."""
    import html as _html

    # Greenhouse returns its content HTML-escaped, so the tags arrive as
    # &lt;p&gt; and a tag-stripping pass would leave them untouched. Unescape
    # first, strip, then unescape again for entities inside the text itself.
    text = _html.unescape(html or "")
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|li|tr|h[1-6])>", "\n", text)
    text = re.sub(r"(?i)<li[^>]*>", "\n- ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = _html.unescape(text)
    text = re.sub(r"[ \t ]+", " ", text)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()


def parse_date(value) -> _dt.date | None:
    """ATS timestamps, in the several shapes they actually arrive in."""
    if not value:
        return None
    if isinstance(value, _dt.datetime):
        return value.date()
    if isinstance(value, _dt.date):
        return value
    text = str(value).strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d", "%m/%d/%Y"):
        try:
            return _dt.datetime.strptime(text[:len(_dt.datetime.now().strftime(fmt))], fmt).date()
        except ValueError:
            continue
    try:
        return _dt.datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


#: Workday says "Posted 30+ Days Ago"; that is a bucket, not a date, so it stays None.
_RELATIVE = re.compile(r"posted\s+(\d+)\+?\s*days?\s*ago", re.I)


def parse_relative(value: str | None) -> _dt.date | None:
    if not value:
        return None
    if re.search(r"posted\s+today", value, re.I):
        return _dt.date.today()
    if re.search(r"posted\s+yesterday", value, re.I):
        return _dt.date.today() - _dt.timedelta(days=1)
    m = _RELATIVE.search(value)
    if m and "+" not in value:
        return _dt.date.today() - _dt.timedelta(days=int(m.group(1)))
    return None
