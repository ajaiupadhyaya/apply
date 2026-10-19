"""Work out which job board a firm uses, from its careers page.

Adding an employer to the registry means knowing its ATS and slug. The
documented way to find that is to open the careers page with devtools on the
Network tab and read the request URL, which is a fine thing to ask an engineer
to do once and a terrible thing to ask anyone to do nine times.

So: fetch the careers page and look for the fingerprints. Most careers sites
either link to their board directly or embed its host in a script tag. The ones
that render entirely in JavaScript defeat this, and those are reported honestly
rather than guessed at.

Worth knowing when a guess fails: a subsidiary often sits on its parent's
Workday tenant rather than its own, so the tenant in the URL is the parent's
name. The careers page carries the right one; guessing does not.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

import httpx

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

#: (ats, regex). The first group is the slug except for Workday, which needs three.
FINGERPRINTS: list[tuple[str, str]] = [
    ("workday", r"([a-z0-9-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:[a-zA-Z-]{2,5}/)?([A-Za-z0-9_]{3,40})"),
    ("greenhouse", r"(?:boards|job-boards)\.greenhouse\.io/([a-z0-9_-]+)"),
    ("greenhouse", r"boards-api\.greenhouse\.io/v1/boards/([a-z0-9_-]+)"),
    ("lever", r"jobs\.lever\.co/([a-z0-9-]+)"),
    ("ashby", r"jobs\.ashbyhq\.com/([a-z0-9-]+)"),
    ("oracle", r"([a-z0-9-]+\.fa(?:\.[a-z0-9-]+)?\.oraclecloud\.com)/hcmUI/CandidateExperience/(?:[a-z-]+/)?sites/(CX_\d+)"),
    ("eightfold", r"([a-z0-9-]+)\.eightfold\.ai"),
    # Recognised but not supported: reporting them beats silently finding nothing.
    ("icims", r"([a-z0-9-]+)\.icims\.com"),
    ("smartrecruiters", r"careers\.smartrecruiters\.com/([A-Za-z0-9]+)"),
    ("eightfold", r"([a-z0-9-]+)\.eightfold\.ai"),
    ("phenom", r"([a-z0-9-]+)\.phenompeople\.com"),
    ("taleo", r"([a-z0-9-]+)\.taleo\.net"),
]

SUPPORTED = {"workday", "greenhouse", "lever", "ashby", "oracle", "eightfold"}

#: Subdomains an Eightfold careers page loads that are not a firm's board.
NOT_A_BOARD = {"static", "cdn", "assets", "app", "www", "api", "help", "docs", "media"}


#: Per-ATS result cap written into a registry entry; as_yaml and as_entry share it.
MAX_RESULTS = {"workday": 120, "eightfold": 300, "oracle": 1000}

#: ATSes whose adapters filter on the entry's `search` terms.
SEARCHED = {"workday", "eightfold", "oracle"}


@dataclass(slots=True)
class Candidate:
    ats: str
    evidence: str
    config: dict
    supported: bool

    def as_yaml(self, name: str, priority: int = 3, search: list[str] | None = None) -> str:
        terms = "    search: [" + ", ".join(json.dumps(t) for t in (search or ["analyst", "intern", "2027"])) + "]"
        lines = [f"  - name: {name}", f"    ats: {self.ats}"]
        for key in ("board", "host", "tenant", "site"):
            if key in self.config:
                lines.append(f"    {key}: {self.config[key]}")
        if self.ats == "workday":
            lines.append(terms)
            lines.append(f"    max_results: {MAX_RESULTS['workday']}")
        elif self.ats == "oracle":
            lines.append(f"    max_results: {MAX_RESULTS['oracle']}")
        elif self.ats == "eightfold":
            lines.append(terms)
            lines.append(f"    max_results: {MAX_RESULTS['eightfold']}")
        lines.append(f"    priority: {priority}")
        return "\n".join(lines)

    def as_entry(self, name: str, priority: int, search: list[str], tracks: list[str]) -> dict:
        entry = {"name": name, "ats": self.ats, **self.config, "tracks": tracks, "priority": priority}
        if self.ats in SEARCHED:
            entry["search"] = search
        if self.ats in MAX_RESULTS:
            entry["max_results"] = MAX_RESULTS[self.ats]
        return entry


def fetch(url: str, timeout: float = 20.0) -> str:
    response = httpx.get(url, timeout=timeout, follow_redirects=True,
                         headers={"User-Agent": BROWSER_UA})
    response.raise_for_status()
    return response.text


def candidates(html: str) -> list[Candidate]:
    """Every board fingerprint in the page, best-supported first, deduplicated."""
    found: dict[str, Candidate] = {}
    for ats, pattern in FINGERPRINTS:
        for match in re.finditer(pattern, html):
            if ats == "workday":
                tenant, wd, site = match.groups()
                if site.lower() in ("wday", "en-us", "job", "jobs"):
                    continue
                config = {"host": f"{tenant}.{wd}.myworkdayjobs.com",
                          "tenant": tenant, "site": site}
            elif ats == "oracle":
                host, site = match.groups()
                config = {"host": host, "site": site}
            elif ats == "eightfold":
                # A careers page also loads Eightfold's own assets; those
                # subdomains are the vendor's, not this firm's board.
                if match.group(1) in NOT_A_BOARD:
                    continue
                config = {"host": f"{match.group(1)}.eightfold.ai"}
            else:
                config = {"board": match.group(1)}
            key = f"{ats}:{'/'.join(str(v) for v in config.values())}"
            found.setdefault(key, Candidate(
                ats=ats, evidence=match.group(0), config=config,
                supported=ats in SUPPORTED,
            ))
    return sorted(found.values(), key=lambda c: (not c.supported, c.ats))


def verify(candidate: Candidate, name: str = "probe", search: list[str] | None = None) -> int | None:
    """Actually call the board. Returns the posting count, or None if it did not answer."""
    from .sources import ADAPTERS

    adapter = ADAPTERS.get(candidate.ats)
    if adapter is None:
        return None
    config = {"name": name, **candidate.config, "search": search or ["analyst"], "max_results": 20}
    try:
        return len(adapter.fetch(config))
    except Exception:                                   # noqa: BLE001
        return None


_LEGAL_SUFFIX = re.compile(r"\b(inc|llc|lp|llp|ltd|plc|corp|corporation|co)\b\.?", re.I)
_DESCRIPTIVE_SUFFIX = re.compile(r"\b(company|group|holdings)\b\.?", re.I)


def slug_candidates(name: str) -> list[str]:
    """The slugs a firm's board most often lives under, most likely first.

    A descriptive tail (Group, Holdings) is dropped only if two words remain, so
    "Man Group" never probes the unrelated board "man"."""
    base = _LEGAL_SUFFIX.sub(" ", name.lower())
    words = re.findall(r"[a-z0-9]+", _DESCRIPTIVE_SUFFIX.sub(" ", base))
    if len(words) < 2:
        words = re.findall(r"[a-z0-9]+", base)
    out = ["".join(words), "-".join(words)]
    if len(words) > 2:
        out.append("".join(words[:-1]))
    return list(dict.fromkeys(s for s in out if s))


def probe_slugs(name: str, verify_fn=None) -> tuple["Candidate", int] | None:
    """Try the public board APIs under the likely slugs. Only an answer with
    postings counts; a guess is never written to the registry."""
    verify_fn = verify_fn or verify
    for slug in slug_candidates(name):
        for ats in ("greenhouse", "lever", "ashby"):
            candidate = Candidate(ats=ats, evidence=f"probed {ats}:{slug}",
                                  config={"board": slug}, supported=True)
            count = verify_fn(candidate, name)
            if count:
                return candidate, count
    return None


def resolve(url: str, *, check: bool = True, name: str = "probe") -> list[tuple[Candidate, int | None]]:
    """Fetch a careers page and return what it is running on."""
    found = candidates(fetch(url))
    if not check:
        return [(c, None) for c in found]
    return [(c, verify(c, name) if c.supported else None) for c in found]


# ------------------------------------------------------ is this host real?

#: apex -> what it is. A posting's link is trusted when its host IS one of these
#: or a subdomain of one; nothing looser. `evil-greenhouse.io`,
#: `boards.greenhouse.io.evil.com` and `https://greenhouse.io@evil.com/` all fail.
KNOWN_HOSTS: dict[str, str] = {
    "greenhouse.io": "greenhouse", "lever.co": "lever", "ashbyhq.com": "ashby",
    "myworkdayjobs.com": "workday", "myworkdaysite.com": "workday",
    "workday.com": "workday", "icims.com": "icims",
    "smartrecruiters.com": "smartrecruiters", "workable.com": "workable",
    "taleo.net": "taleo", "oraclecloud.com": "oracle", "eightfold.ai": "eightfold",
    "phenompeople.com": "phenom", "jobvite.com": "jobvite",
    "successfactors.com": "successfactors", "successfactors.eu": "successfactors",
    "linkedin.com": "linkedin", "joinhandshake.com": "handshake",
    "indeed.com": "indeed", "efinancialcareers.com": "efinancialcareers",
}


def _squash(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def host_check(url: str | None, company: str | None = None) -> tuple[str, str] | None:
    """('ats', name) | ('employer', host) | ('unverified', host); None without a URL.

    Adapted from ai-job-search's source-host step. A host that is neither a
    known job board nor plausibly the employer's own domain is named plainly so
    the owner verifies the firm before spending a letter on it: fake postings
    for finance internships are a known lure.
    """
    from urllib.parse import urlparse

    if not url:
        return None
    host = (urlparse(url if "//" in url else f"//{url}").hostname or "").lower().rstrip(".")
    if not host:
        return ("unverified", url)
    for apex, name in KNOWN_HOSTS.items():
        if host == apex or host.endswith("." + apex):
            return ("ats", name)
    if company:
        # "careers.janestreet.com" for Jane Street. The registrable label must BE
        # the firm's name, not contain it: "citadel-careers.xyz" is the lure.
        labels = host.split(".")
        registrable = labels[-2] if len(labels) >= 2 else host
        words = [w for w in re.findall(r"[a-z0-9]+", company.lower())
                 if w not in {"the", "and", "of", "group", "inc", "llc", "lp", "co"}]
        if words and registrable in {"".join(words), words[0], "".join(words[:2])}:
            return ("employer", host)
    return ("unverified", host)
