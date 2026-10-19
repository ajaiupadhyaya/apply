"""Eightfold: the API a talent-marketplace careers page renders from.

Several large firms run their careers site on Eightfold rather than on a job
board of their own. The page is JavaScript, so it carries no listings to read,
but the endpoint behind it is public and answers a plain GET: a list of
requisitions, ten at a time, and a detail resource per requisition.

Two steps, like Workday and Oracle: the list gives a title, locations and a
date, and the description needs a second request per posting — so hydration
stays separate and the gate throws most of them away for free first.

Not every Eightfold board is readable. Some sit behind bot protection and
answer a non-browser client with 403; those are not polled, and their postings
arrive through alert mail instead.

Config: `host` (<firm>.eightfold.ai), optionally `domain` (the firm's own
domain, which its careers page sends and which the API validates when present),
`search` (keywords; empty means the whole board) and `max_results`.
"""

from __future__ import annotations

import datetime as _dt

import httpx

from . import ats
from .ats import _common, _get
from .base import RawPosting, SourceError, strip_html


class Eightfold:
    name = "eightfold"
    #: The API returns ten whatever `num` asks for, so this is its page, not a choice.
    PAGE = 10

    def _url(self, config: dict) -> str:
        return f"https://{config['host'].rstrip('/')}/api/apply/v2/jobs"

    def _params(self, config: dict, start: int, num: int, term: str) -> dict:
        params: dict[str, object] = {"start": start, "num": num}
        if config.get("domain"):
            params["domain"] = config["domain"]
        if term:
            params["query"] = term
        return params

    def fetch(self, config: dict) -> list[RawPosting]:
        url = self._url(config)
        limit = int(config.get("max_results", 100))
        seen: dict[str, RawPosting] = {}
        try:
            with ats._client() as client:
                for term in config.get("search") or [""]:
                    start = 0
                    while start < limit:
                        size = min(self.PAGE, limit - start)
                        payload = _get(client, url,
                                       params=self._params(config, start, size, term)).json()
                        page = payload.get("positions") or []
                        for job in page[:size]:
                            if job.get("isPrivate"):
                                continue
                            job_id = str(job.get("id", ""))
                            if job_id and job_id not in seen:
                                seen[job_id] = self._posting(job, config)
                        start += size
                        if not page or start >= int(payload.get("count") or 0):
                            break
        except (httpx.HTTPError, ValueError) as exc:
            raise SourceError(f"eightfold/{config.get('host')}: {exc}") from exc
        return list(seen.values())

    def _posting(self, job: dict, config: dict) -> RawPosting:
        job_id = str(job.get("id", ""))
        places = job.get("locations") or [job.get("location")]
        return RawPosting(
            employer=config["name"],
            title=job.get("name") or job.get("posting_name", ""),
            url=job.get("canonicalPositionUrl")
                or f"https://{config['host']}/careers/job/{job_id}",
            source=self.name,
            external_id=job_id,
            location="; ".join(p for p in places if p) or None,
            description=strip_html(job.get("job_description") or ""),
            posted_at=_epoch(job.get("t_create")),
            raw=job,
            **_common(config),
        )

    def hydrate(self, posting: RawPosting, config: dict) -> RawPosting:
        try:
            with ats._client() as client:
                info = _get(client, f"{self._url(config)}/{posting.external_id}",
                            params=self._params(config, 0, 1, "")).json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SourceError(f"eightfold hydrate {posting.external_id}: {exc}") from exc

        body = strip_html(info.get("job_description") or "")
        if body:
            posting.description = body
        posting.posted_at = _epoch(info.get("t_create")) or posting.posted_at
        return posting


def _epoch(value) -> _dt.date | None:
    """A Unix timestamp as the date it falls on in UTC.

    The boards set these to midnight UTC, so reading them in local time would
    move every posting a day earlier for anyone west of Greenwich.
    """
    try:
        return _dt.datetime.fromtimestamp(int(value), _dt.timezone.utc).date()
    except (TypeError, ValueError, OSError):
        return None


ADAPTERS: dict[str, object] = {Eightfold.name: Eightfold()}
