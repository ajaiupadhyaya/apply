"""Adapters for the public job-board APIs.

Greenhouse, Lever and Ashby publish documented, unauthenticated endpoints that
serve exactly the data their public careers pages show. Workday and Oracle
Recruiting Cloud do not document one, but each of their careers sites is a
single-page app that calls its own JSON endpoint — the same public data, one
layer down.

Which adapter a firm needs is a property of the firm, not of this module.
Greenhouse, Lever and Ashby want one slug — the one already in their careers
URL — and `apply resolve` reads it off the page. Workday and Oracle want a
tenant and a site slug, which usually have to be looked up once, by hand, and
written into employers.yaml. That is the whole maintenance burden: a line per
employer, set once, and no credential anywhere.
"""

from __future__ import annotations

import re

import httpx

from .. import __version__
from .base import (
    RawPosting, SourceError, parse_date, parse_local_date, parse_relative, strip_html,
)

TIMEOUT = httpx.Timeout(20.0, connect=10.0)
#: Honest identification, and nobody's name. This reads public job boards on one
#: person's behalf — but which person depends on who is running the clone, so
#: the string says what the software is and how much traffic to expect, and
#: leaves the operator out of it rather than claiming to be its author.
USER_AGENT = f"apply/{__version__} (personal job-application tracker; one user)"
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json",
}


def _client() -> httpx.Client:
    return httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True)


def _get(client: httpx.Client, url: str, *, params: dict | None = None,
         attempts: int = 3, backoff: float = 2.0) -> httpx.Response:
    """A GET that survives one dropped connection.

    A board fetched 200 postings at a time is two dozen requests, and one
    transient timeout in the middle should not cost the other twenty-five. Only
    transport failures are retried; an HTTP error status is an answer.
    """
    import time

    for attempt in range(attempts):
        try:
            response = client.get(url, params=params)
            response.raise_for_status()
            return response
        except httpx.TransportError:
            if attempt == attempts - 1:
                raise
            time.sleep(backoff * (attempt + 1))
    raise AssertionError("unreachable")


def _common(config: dict) -> dict:
    return {
        "employer_priority": int(config.get("priority", 3)),
        "employer_tracks": tuple(config.get("tracks") or ()),
        "employer_senior_grades": tuple(config.get("senior_grades") or ()),
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


def _is_a_place(value: str) -> bool:
    """Whether a Workday bullet is a location rather than a requisition id.

    A tenant decides for itself what goes in `bulletFields`, and they do not
    agree: one sends the req id alone, one sends the id and a department, and
    one omits `locationsText` entirely and puts the place first. Read
    positionally, that place became the posting's id, so every row deduplicated
    against the wrong key and the geography gate saw nothing.

    A place has a separator with spaces around it; a req id ("JR-0000122333",
    "R-0012229", "45027") never does.
    """
    return ", " in value or " - " in value


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
                            bullets = [str(b) for b in (job.get("bulletFields") or []) if b]
                            places = [b for b in bullets if _is_a_place(b)]
                            ids = [b for b in bullets if not _is_a_place(b)]
                            seen[path] = RawPosting(
                                employer=config["name"],
                                title=job.get("title", ""),
                                url=workday_page_url(config, path),
                                source=self.name,
                                external_id=ids[0] if ids else path,
                                location=job.get("locationsText") or (places[0] if places else None),
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
        # Some tenants' externalUrl has no site in it either; keep the link
        # fetch() built rather than trade a working one for a 404.
        if info.get("externalUrl") and not is_siteless_workday(info["externalUrl"]):
            posting.url = info["externalUrl"]
        return posting


_LOCALE = re.compile(r"[a-z]{2}-[A-Z]{2}")
_SHARED_HOST = (".myworkdaysite.com",)
_WORKDAY_HOSTS = (".myworkdayjobs.com", ".myworkdaysite.com")


def workday_page_url(config: dict, path: str) -> str:
    """The page a person opens for a Workday posting.

    `externalPath` ("/job/<loc>/<slug>") carries no site, and a link without one
    is a 404 in a browser. A tenant host takes the site as its first segment; a
    shared host (wdN.myworkdaysite.com) serves every tenant under /recruiting/.
    """
    if config.get("site_url"):
        return config["site_url"].rstrip("/") + path
    host = config["host"].rstrip("/")
    if host.endswith(_SHARED_HOST):
        return f"https://{host}/recruiting/{config['tenant']}/{config['site']}{path}"
    return f"https://{host}/{config['site']}{path}"


def _workday_parts(url: str) -> tuple[str, list[str]] | None:
    parsed = httpx.URL(url)
    host = parsed.host or ""
    if not host.endswith(_WORKDAY_HOSTS):
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if parts and _LOCALE.fullmatch(parts[0]):
        parts = parts[1:]
    return host, parts


def workday_api_url(url: str, site: str | None = None, tenant: str | None = None) -> str | None:
    """The cxs endpoint behind a Workday job page, or None if it cannot be told.

      https://<tenant>.wdN.myworkdayjobs.com/[en-US/]<site>/job/<loc>/<slug>
      https://wdN.myworkdaysite.com/recruiting/<tenant>/<site>/job/<loc>/<slug>
        -> https://<host>/wday/cxs/<tenant>/<site>/job/<loc>/<slug>

    A link with no site in it ("/job/..." straight after the host) needs `site`
    (and, on a shared host, `tenant`) from the registry; without them, None.
    """
    found = _workday_parts(url)
    if found is None:
        return None
    host, parts = found
    if len(parts) >= 5 and parts[0] == "recruiting" and parts[3] == "job":
        tenant_, site_, rest = parts[1], parts[2], parts[3:]
    elif len(parts) >= 3 and parts[1] == "job" and parts[0] not in ("wday", "recruiting"):
        tenant_, site_, rest = host.split(".")[0], parts[0], parts[1:]
    elif len(parts) >= 2 and parts[0] == "job" and site:
        tenant_ = tenant or host.split(".")[0]
        site_, rest = site, parts
    else:
        return None
    return f"https://{host}/wday/cxs/{tenant_}/{site_}/" + "/".join(rest)


def is_siteless_workday(url: str) -> bool:
    found = _workday_parts(url)
    return bool(found) and bool(found[1]) and found[1][0] == "job"


def repaired_workday_url(url: str, tenant: str, site: str) -> str:
    """A site-less link with its site put back, in the form discovery now writes."""
    host, parts = _workday_parts(url)                       # type: ignore[misc]
    return workday_page_url({"host": host, "tenant": tenant, "site": site},
                            "/" + "/".join(parts))


def workday_posting_state(client: httpx.Client, url: str,
                          get=None) -> tuple[str, str] | None:
    """(state, reason) from Workday's own API, or None when `url` is not Workday.

    A live posting answers 200. A removed one answers 404, or 403 with Workday's
    error code S22 ("permission denied"): the requisition is no longer public.
    A 403 without that code is an ordinary block and says nothing. `get` is the
    request to use (the sweep passes one that waits out a 429).
    """
    api = workday_api_url(url)
    if api is None:
        return None
    get = get or (lambda u: client.get(u, headers={"Accept": "application/json"}))
    try:
        response = get(api)
    except httpx.HTTPError as exc:
        return "unreachable", type(exc).__name__
    if response.status_code == 200:
        return "open", ""
    if response.status_code == 404:
        return "closed", "Workday: no such posting (404)"
    if response.status_code == 403:
        try:
            code = (response.json() or {}).get("errorCode")
        except ValueError:
            code = None
        if code == "S22":
            return "closed", "Workday: the posting is no longer public (403 S22)"
    return "unreachable", f"Workday API {response.status_code}"


# ----------------------------------------------------------------- oracle


class Oracle:
    """Oracle Recruiting Cloud: the REST resource its Candidate Experience
    site calls to render itself.

    One firm's whole board, 200 postings a request. The listing carries a title,
    locations and a one-line summary; the description and the application
    deadline (`ExternalPostedEndDate`, a real close time) need a second request
    per posting, so they wait for hydration like Workday's.

    Config: `host` (<tenant>.fa.<region>.oraclecloud.com), `site` (CX_1001 or
    similar), and optionally `location_id` (a location facet id, to skip
    whole countries the scorer would reject anyway), `search` (keywords; empty
    means everything) and `max_results`.
    """

    name = "oracle"
    PAGE = 200
    RESOURCE = "hcmRestApi/resources/latest"

    def _base(self, config: dict) -> str:
        return f"https://{config['host'].rstrip('/')}/{self.RESOURCE}"

    def job_url(self, config: dict, req_id: str) -> str:
        return (f"https://{config['host'].rstrip('/')}/hcmUI/CandidateExperience/en/"
                f"sites/{config['site']}/job/{req_id}")

    def _finder(self, config: dict, offset: int, term: str, size: int) -> str:
        parts = [f"siteNumber={config['site']}", f"limit={size}", f"offset={offset}",
                 "sortBy=POSTING_DATES_DESC"]
        if config.get("location_id"):
            parts.append(f"locationId={config['location_id']}")
        if term:
            parts.append(f'keyword="{term}"')
        return "findReqs;" + ",".join(parts)

    def fetch(self, config: dict) -> list[RawPosting]:
        url = f"{self._base(config)}/recruitingCEJobRequisitions"
        limit = int(config.get("max_results", 100))
        seen: dict[str, RawPosting] = {}
        try:
            with _client() as client:
                for term in config.get("search") or [""]:
                    offset = 0
                    while offset < limit:
                        # The last request asks only for what is left under the cap.
                        size = min(self.PAGE, limit - offset)
                        response = _get(client, url, params={
                            "onlyData": "true",
                            "expand": "requisitionList.secondaryLocations",
                            "finder": self._finder(config, offset, term, size),
                        })
                        items = response.json().get("items") or [{}]
                        page = items[0].get("requisitionList") or []
                        for job in page[:size]:
                            req_id = str(job.get("Id", ""))
                            if req_id and req_id not in seen:
                                seen[req_id] = self._posting(job, config)
                        offset += size
                        if not page or offset >= int(items[0].get("TotalJobsCount") or 0):
                            break
        except (httpx.HTTPError, ValueError) as exc:
            raise SourceError(f"oracle/{config.get('host')}: {exc}") from exc
        return list(seen.values())

    def _posting(self, job: dict, config: dict) -> RawPosting:
        req_id = str(job.get("Id", ""))
        places = [job.get("PrimaryLocation")] + [
            s.get("Name") for s in (job.get("secondaryLocations") or [])]
        summary = "\n\n".join(strip_html(job.get(k) or "") for k in (
            "ShortDescriptionStr", "ExternalResponsibilitiesStr", "ExternalQualificationsStr"))
        return RawPosting(
            employer=config["name"],
            title=job.get("Title", ""),
            url=self.job_url(config, req_id),
            source=self.name,
            external_id=req_id,
            location="; ".join(p for p in places if p) or None,
            description=summary.strip(),
            posted_at=parse_date(job.get("PostedDate")),
            deadline=parse_local_date(job.get("PostingEndDate")),
            raw=job,
            **_common(config),
        )

    def hydrate(self, posting: RawPosting, config: dict) -> RawPosting:
        try:
            with _client() as client:
                response = _get(
                    client, f"{self._base(config)}/recruitingCEJobRequisitionDetails",
                    params={"onlyData": "true", "expand": "all",
                            "finder": f'ById;Id="{posting.external_id}",siteNumber={config["site"]}'},
                )
                info = (response.json().get("items") or [{}])[0]
        except (httpx.HTTPError, ValueError) as exc:
            raise SourceError(f"oracle hydrate {posting.external_id}: {exc}") from exc

        # Every section, in the order the page shows them. The firm-wide "about
        # us" goes last: it is boilerplate, but it is the source text.
        sections = [strip_html(info.get(k) or "") for k in (
            "ExternalDescriptionStr", "ExternalResponsibilitiesStr",
            "ExternalQualificationsStr", "OrganizationDescriptionStr",
            "CorporateDescriptionStr")]
        body = "\n\n".join(s for s in sections if s)
        if body:
            posting.description = body
        posting.posted_at = parse_date(info.get("ExternalPostedStartDate")) or posting.posted_at
        posting.deadline = parse_local_date(info.get("ExternalPostedEndDate")) or posting.deadline
        return posting


ADAPTERS: dict[str, object] = {
    a.name: a() for a in (Greenhouse, Lever, Ashby, Workday, Oracle)
}
