"""Careers pages that carry their own listings.

A Next.js site renders from a JSON blob it embeds in the page as
`<script id="__NEXT_DATA__">`. When a firm's careers page is built that way and
has no job-board API behind it, the blob *is* the job board: the same records
the page draws, public, in one GET. This reads that blob and nothing else — no
link is followed, no second page is requested, nothing is sent. Check the
firm's robots.txt before adding one; the page this was written for allows it.

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

import httpx

from .ats import HEADERS, TIMEOUT, _common
from .base import RawPosting, SourceError, parse_local_date, strip_html

_BLOB = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_EMPLOYEES_ONLY = re.compile(r"internal", re.I)


class NextData:
    name = "nextdata"
    DEFAULT_LISTS = ("regularJobs", "internships")

    def fetch(self, config: dict) -> list[RawPosting]:
        url = config["url"]
        try:
            with httpx.Client(timeout=TIMEOUT, follow_redirects=True,
                              headers={**HEADERS, "Accept": "text/html"}) as client:
                response = client.get(url)
                response.raise_for_status()
                page = response.text
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
