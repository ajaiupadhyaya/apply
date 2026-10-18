"""Work out which job board a firm uses, from its careers page.

Adding an employer to the registry means knowing its ATS and slug. The
documented way to find that is to open the careers page with devtools on the
Network tab and read the request URL, which is a fine thing to ask an engineer
to do once and a terrible thing to ask anyone to do nine times.

So: fetch the careers page and look for the fingerprints. Most careers sites
either link to their board directly or embed its host in a script tag. The ones
that render entirely in JavaScript defeat this, and those are reported honestly
rather than guessed at.

Resolved live on 2026-09-20: Capital One (Workday, capitalone/Capital_One),
Harris Williams (Workday, on PNC's tenant — pnc/HarrisWilliams), and the Federal
Reserve (Workday, rb/FRS).
"""

from __future__ import annotations

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
    # Recognised but not supported: reporting them beats silently finding nothing.
    ("icims", r"([a-z0-9-]+)\.icims\.com"),
    ("smartrecruiters", r"careers\.smartrecruiters\.com/([A-Za-z0-9]+)"),
    ("eightfold", r"([a-z0-9-]+)\.eightfold\.ai"),
    ("phenom", r"([a-z0-9-]+)\.phenompeople\.com"),
    ("taleo", r"([a-z0-9-]+)\.taleo\.net"),
]

SUPPORTED = {"workday", "greenhouse", "lever", "ashby"}


@dataclass(slots=True)
class Candidate:
    ats: str
    evidence: str
    config: dict
    supported: bool

    def as_yaml(self, name: str, priority: int = 3) -> str:
        lines = [f"  - name: {name}", f"    ats: {self.ats}"]
        for key in ("board", "host", "tenant", "site"):
            if key in self.config:
                lines.append(f"    {key}: {self.config[key]}")
        if self.ats == "workday":
            lines.append('    search: ["analyst", "intern", "2027"]')
            lines.append("    max_results: 120")
        lines.append(f"    priority: {priority}")
        return "\n".join(lines)


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
            else:
                config = {"board": match.group(1)}
            key = f"{ats}:{'/'.join(str(v) for v in config.values())}"
            found.setdefault(key, Candidate(
                ats=ats, evidence=match.group(0), config=config,
                supported=ats in SUPPORTED,
            ))
    return sorted(found.values(), key=lambda c: (not c.supported, c.ats))


def verify(candidate: Candidate, name: str = "probe") -> int | None:
    """Actually call the board. Returns the posting count, or None if it did not answer."""
    from .sources import ADAPTERS

    adapter = ADAPTERS.get(candidate.ats)
    if adapter is None:
        return None
    config = {"name": name, **candidate.config, "search": ["analyst"], "max_results": 20}
    try:
        return len(adapter.fetch(config))
    except Exception:                                   # noqa: BLE001
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
