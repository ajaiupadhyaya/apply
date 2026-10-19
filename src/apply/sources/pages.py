"""Careers pages that carry their own listings.

A Next.js site renders from a JSON blob it embeds in the page as
`<script id="__NEXT_DATA__">`. When a firm's careers page is built that way and
has no job-board API behind it, the blob *is* the job board: the same records
the page draws, public, in one GET. This reads that blob and nothing else — no
link is followed, no second page is requested, nothing is sent. The site's
robots.txt is read first, and a page it disallows is never requested.

The record shape (`displayName`, `jobDescription`, `jobMetadata.jobLocations`)
is the one the firm this was written for uses. A firm with a different shape
needs its own `_posting`, not a guess.

Config: `url` (the careers page) and `lists`, the keys under
`props.pageProps` that hold listings. A list whose name says it is internal is
never read, even if configured: those roles are for current employees.
"""

from __future__ import annotations

import json
import re
from urllib.robotparser import RobotFileParser

import httpx

from . import ats
from .ats import _common, _get
from .base import RawPosting, SourceError, parse_local_date, strip_html

_BLOB = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_EMPLOYEES_ONLY = re.compile(r"internal", re.I)


def robots_allows(client: httpx.Client, url: str, user_agent: str) -> tuple[bool, str]:
    """Whether the site's robots.txt lets `user_agent` read `url`, and if not, why.

    RFC 9309: a robots.txt that does not exist (any 4xx) allows everything; one
    that cannot be read (5xx, or no connection) allows nothing.
    """
    target = httpx.URL(url)
    robots = str(target.copy_with(path="/robots.txt", query=None, fragment=None))
    try:
        response = client.get(robots)
    except httpx.HTTPError as exc:
        return False, f"{robots} could not be read ({type(exc).__name__}); not reading the page"
    if 400 <= response.status_code < 500:
        return True, ""
    if response.status_code >= 500:
        return False, f"{robots} answered {response.status_code}; not reading the page"
    parser = RobotFileParser()
    parser.parse(response.text.splitlines())
    agent = user_agent.split("/")[0].split()[0]
    if parser.can_fetch(agent, url):
        return True, ""
    return False, f"{robots} disallows {target.path}"


class NextData:
    name = "nextdata"
    DEFAULT_LISTS = ("regularJobs", "internships")

    def fetch(self, config: dict) -> list[RawPosting]:
        url = config["url"]
        try:
            with ats._client() as client:
                allowed, why = robots_allows(client, url, ats.USER_AGENT)
                if not allowed:
                    raise SourceError(f"nextdata/{url}: {why}")
                client.headers["Accept"] = "text/html"
                page = _get(client, url).text
        except httpx.HTTPError as exc:
            raise SourceError(f"nextdata/{url}: {exc}") from exc
        return self.parse(page, config)

    def parse(self, page: str, config: dict) -> list[RawPosting]:
        url = config["url"]
        match = _BLOB.search(page)
        if not match:
            raise SourceError(f"nextdata/{url}: no __NEXT_DATA__ in the page — it changed shape")
        try:
            props = json.loads(match.group(1))["props"]["pageProps"]
        except (ValueError, KeyError) as exc:
            raise SourceError(f"nextdata/{url}: unreadable page data ({exc})") from exc
        if props.get("jobsFetchingError"):
            raise SourceError(f"nextdata/{url}: the page reports it could not load its jobs")

        out: dict[str, RawPosting] = {}
        for key in config.get("lists") or self.DEFAULT_LISTS:
            if _EMPLOYEES_ONLY.search(key):
                continue
            if key not in props:
                # A renamed list must fail loudly; a silent zero looks like a quiet week.
                raise SourceError(f"nextdata/{url}: no list {key!r} (has: {', '.join(props)})")
            for item in props[key] or []:
                record = item.get("data", item)
                if not record.get("activeOnJobsListing", True):
                    continue
                posting = self._posting(record, config)
                out.setdefault(posting.external_id, posting)
        return list(out.values())

    def _posting(self, record: dict, config: dict) -> RawPosting:
        meta = record.get("jobMetadata") or {}
        places = [loc.get("name") for loc in meta.get("jobLocations") or []]
        base = (config.get("job_base") or config["url"]).rstrip("/")
        return RawPosting(
            employer=config["name"],
            title=record.get("displayName", ""),
            url=f"{base}/{record.get('jobUrl', '')}",
            source=self.name,
            external_id=str(record.get("id", "")),
            location="; ".join(p for p in places if p) or None,
            description=_description(record),
            deadline=parse_local_date(record.get("validToDate")),
            raw=record,
            **_common(config),
        )

    def hydrate(self, posting: RawPosting, config: dict) -> RawPosting:
        return posting          # the page carries the whole description


def _description(record: dict) -> str:
    """Every text field the listing has, labelled by the field it came from."""
    text = record.get("jobDescription") or {}
    meta = record.get("jobMetadata") or {}

    responsibilities = (strip_html(text.get("responsibilitiesHtml") or "")
                        or strip_html(text.get("responsibilities") or ""))
    people = (strip_html(text.get("peopleWeAreLookingForHtml") or "")
              or "\n".join(f"- {p.strip()}" for p in text.get("peopleWeAreLookingFor") or [])
              or (text.get("peopleWeAreLookingForStr") or "").strip())
    facts = " · ".join(v for v in (
        meta.get("workStatus"),
        (record.get("department") or {}).get("name"),
        meta.get("jobSeekerCategoriesString"),
    ) if v)

    sections = [
        strip_html(text.get("websiteDescription") or ""),
        strip_html(text.get("hhDescription") or ""),
        f"Responsibilities\n{responsibilities}" if responsibilities else "",
        f"People we are looking for\n{people}" if people else "",
        facts,
    ]
    return "\n\n".join(s for s in sections if s)


ADAPTERS: dict[str, object] = {NextData.name: NextData()}
