"""Adapters for the public job-board APIs.

Greenhouse, Lever and Ashby publish documented, unauthenticated endpoints that
serve exactly the data their public careers pages show. Workday does not
document one, but every Workday careers site is a single-page app that calls its
own `/wday/cxs/` JSON endpoint — the same public data, one layer down.

Measured coverage across the target list (2026-09-20): Jane Street, IMC and
Optiver answer on Greenhouse; BlackRock answers on Workday. The banks and
insurers each need their tenant and site slug looked up once, by hand, and
written into employers.yaml. That is the whole maintenance burden: a line per
employer, set once.
"""

from __future__ import annotations

import httpx

from .base import RawPosting, SourceError, parse_date, parse_relative, strip_html

TIMEOUT = httpx.Timeout(20.0, connect=10.0)
HEADERS = {
    # Honest identification. This reads public job boards on one person's behalf.
    "User-Agent": "apply/0.2 (personal job tracker; one user; +https://github.com/ajaiupadhyaya)",
    "Accept": "application/json",
}


def _client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True)


def _common(config: dict) -> dict:
    return {
        "employer_priority": int(config.get("priority", 3)),
        "employer_tracks": tuple(config.get("tracks") or ()),
    }


# ------------------------------------------------------------- greenhouse


class Greenhouse:
    """https://boards-api.greenhouse.io/v1/boards/<board>/jobs

    `content=true` returns the full description inline, so a Greenhouse employer
    needs exactly one request per run no matter how many postings it has.
    """

    name = "greenhouse"

    def fetch(self, config: dict) -> list[RawPosting]:
        board = config["board"]
        url = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true"
        try:
            with _client() as client:
                response = client.get(url)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SourceError(f"greenhouse/{board}: {exc}") from exc

        out = []
        for job in payload.get("jobs", []):
            location = (job.get("location") or {}).get("name")
            out.append(RawPosting(
                employer=config["name"],
                title=job.get("title", ""),
                url=job.get("absolute_url", ""),
                source=self.name,
                external_id=str(job.get("id", "")),
                location=location,
                description=strip_html(job.get("content", "") or ""),
                posted_at=parse_date(job.get("first_published") or job.get("updated_at")),
                # Greenhouse has the field but employers almost never fill it in.
                # Empty stays empty: a deadline is never inferred.
                deadline=parse_date(job.get("application_deadline")),
                raw=job,
                **_common(config),
            ))
        return out

    def hydrate(self, posting: RawPosting, config: dict) -> RawPosting:
        return posting          # already hydrated by fetch


# ------------------------------------------------------------------ lever


class Lever:
    """https://api.lever.co/v0/postings/<company>?mode=json"""

    name = "lever"

    def fetch(self, config: dict) -> list[RawPosting]:
        company = config["board"]
        url = f"https://api.lever.co/v0/postings/{company}?mode=json"
        try:
            with _client() as client:
                response = client.get(url)
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SourceError(f"lever/{company}: {exc}") from exc

        out = []
        for job in payload:
            categories = job.get("categories") or {}
            body = job.get("descriptionPlain") or strip_html(job.get("description", ""))
            lists = "\n\n".join(
                f"{item.get('text','')}\n{strip_html(item.get('content',''))}"
                for item in (job.get("lists") or [])
            )
            out.append(RawPosting(
                employer=config["name"],
                title=job.get("text", ""),
                url=job.get("hostedUrl", ""),
                source=self.name,
                external_id=str(job.get("id", "")),
                location=categories.get("location"),
                description=(body + "\n\n" + lists).strip(),
                posted_at=parse_date(job.get("createdAt")),
                raw=job,
                **_common(config),
            ))
        return out

    def hydrate(self, posting: RawPosting, config: dict) -> RawPosting:
        return posting


# ------------------------------------------------------------------ ashby


class Ashby:
    """https://api.ashbyhq.com/posting-api/job-board/<name>?includeCompensation=true"""

    name = "ashby"

    def fetch(self, config: dict) -> list[RawPosting]:
        board = config["board"]
        url = f"https://api.ashbyhq.com/posting-api/job-board/{board}"
        try:
            with _client() as client:
                response = client.get(url, params={"includeCompensation": "true"})
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SourceError(f"ashby/{board}: {exc}") from exc

        out = []
        for job in payload.get("jobs", []):
            out.append(RawPosting(
                employer=config["name"],
                title=job.get("title", ""),
                url=job.get("jobUrl", ""),
                source=self.name,
                external_id=str(job.get("id", "")),
                location=job.get("location"),
                description=strip_html(job.get("descriptionHtml", "") or ""),
                posted_at=parse_date(job.get("publishedAt")),
                raw=job,
                **_common(config),
            ))
        return out

    def hydrate(self, posting: RawPosting, config: dict) -> RawPosting:
        return posting


# ---------------------------------------------------------------- workday


class Workday:
    """The endpoint a Workday careers page calls to render itself.

    Two steps, unlike the others: the list gives titles and an `externalPath`,
    and the description needs a second request per posting. That is why
    hydration is separated from fetching everywhere in this module — a Workday
    employer with 400 openings should cost one request, not four hundred, until
    scoring has thrown most of them away.
    """

    name = "workday"
    PAGE = 20

    def _base(self, config: dict) -> str:
        host = config["host"].rstrip("/")
        return f"https://{host}/wday/cxs/{config['tenant']}/{config['site']}"

    def fetch(self, config: dict) -> list[RawPosting]:
        base = self._base(config)
        searches = config.get("search") or [""]
        limit = int(config.get("max_results", 100))

        seen: dict[str, RawPosting] = {}
        try:
            with _client() as client:
                for term in searches:
                    offset = 0
                    while offset < limit:
                        response = client.post(
                            f"{base}/jobs",
                            json={"appliedFacets": {}, "limit": self.PAGE,
                                  "offset": offset, "searchText": term},
                            headers={"Content-Type": "application/json"},
                        )
                        response.raise_for_status()
                        payload = response.json()
                        postings = payload.get("jobPostings") or []
                        if not postings:
                            break
                        for job in postings:
                            path = job.get("externalPath", "")
                            if not path or path in seen:
                                continue
                            seen[path] = RawPosting(
                                employer=config["name"],
                                title=job.get("title", ""),
                                url=config.get("site_url", "").rstrip("/") + path
                                    if config.get("site_url")
                                    else f"https://{config['host']}{path}",
                                source=self.name,
                                external_id=job.get("bulletFields", [path])[0] or path,
                                location=job.get("locationsText"),
                                # "Posted 30+ Days Ago" is a bucket, not a date.
                                posted_at=parse_relative(job.get("postedOn")),
                                raw={**job, "_path": path},
                                **_common(config),
                            )
                        offset += self.PAGE
                        if offset >= (payload.get("total") or 0):
                            break
        except (httpx.HTTPError, ValueError) as exc:
            raise SourceError(f"workday/{config.get('tenant')}: {exc}") from exc
        return list(seen.values())

    def hydrate(self, posting: RawPosting, config: dict) -> RawPosting:
        path = posting.raw.get("_path")
        if not path:
            return posting
        try:
            with _client() as client:
                response = client.get(f"{self._base(config)}{path}")
                response.raise_for_status()
                info = (response.json() or {}).get("jobPostingInfo") or {}
        except (httpx.HTTPError, ValueError) as exc:
            raise SourceError(f"workday hydrate {path}: {exc}") from exc

        posting.description = strip_html(info.get("jobDescription", "") or "")
        posting.posted_at = parse_date(info.get("startDate")) or posting.posted_at
        posting.deadline = parse_date(info.get("endDate")) or posting.deadline
        if info.get("externalUrl"):
            posting.url = info["externalUrl"]
        return posting


ADAPTERS: dict[str, object] = {
    a.name: a() for a in (Greenhouse, Lever, Ashby, Workday)
}
