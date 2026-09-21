"""The Oracle and embedded-page adapters, the budget's deferral, and the title
gates a live pass on those boards showed were missing.

Offline: every request goes to an httpx.MockTransport. The shapes below are
trimmed from what the live boards returned on 2026-09-21, with names replaced.
"""

from __future__ import annotations

import datetime as _dt
import json
import time
from zoneinfo import ZoneInfo

import httpx
import pytest

from apply import discover, resolve
from apply.score import Verdict, score
from apply.sources import ADAPTERS, ats, pages
from apply.sources.base import RawPosting, SourceError, parse_local_date

EASTERN = ZoneInfo("America/New_York")


@pytest.fixture
def eastern(monkeypatch):
    """Run as if on a machine in the owner's timezone."""
    monkeypatch.setenv("TZ", "America/New_York")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


def mock(monkeypatch, handler):
    """Route every adapter request through `handler`; return the request log."""
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    monkeypatch.setattr(ats, "_client", lambda: httpx.Client(
        transport=httpx.MockTransport(record), headers=ats.HEADERS))
    return seen


# ------------------------------------------------------------------ dates


def test_a_utc_close_time_is_filed_on_the_owners_date():
    """11:55 pm Eastern arrives as 03:55 UTC the next day. A day late is the
    one direction a deadline may never be wrong in."""
    assert parse_local_date("2026-10-01T03:55:00+00:00", EASTERN) == _dt.date(2026, 9, 30)


@pytest.mark.parametrize("value,expected", [
    ("2026-10-01", _dt.date(2026, 10, 1)),
    ("2026-10-01T12:00:00", _dt.date(2026, 10, 1)),
    (None, None),
    ("", None),
    ("not a date", None),
])
def test_local_dates_without_an_offset_are_taken_as_written(value, expected):
    assert parse_local_date(value, EASTERN) == expected


# ----------------------------------------------------------------- oracle

ORACLE = {"name": "Example Capital", "ats": "oracle", "host": "example.fa.us2.oraclecloud.com",
          "site": "CX_1", "location_id": 42, "max_results": 100, "priority": 1}


def requisition(n: int, **kw) -> dict:
    return {"Id": str(n), "Title": f"2027 Summer Analyst Program {n}",
            "PrimaryLocation": "New York, NY, United States", "PostedDate": "2026-09-01",
            "PostingEndDate": None, "ShortDescriptionStr": "A ten-week programme.",
            "ExternalResponsibilitiesStr": None, "ExternalQualificationsStr": None,
            "secondaryLocations": [], **kw}


def oracle_list(total: list[dict]):
    def handler(request: httpx.Request) -> httpx.Response:
        finder = request.url.params["finder"]
        fields = dict(part.split("=", 1) for part in finder.split(";", 1)[1].split(","))
        offset, limit = int(fields["offset"]), int(fields["limit"])
        return httpx.Response(200, json={"items": [{
            "TotalJobsCount": len(total),
            "requisitionList": total[offset:offset + limit]}]})
    return handler


def test_oracle_pages_through_the_whole_board(monkeypatch):
    monkeypatch.setattr(ats.Oracle, "PAGE", 2)
    reqs = [requisition(n) for n in range(5)]
    seen = mock(monkeypatch, oracle_list(reqs))

    got = ADAPTERS["oracle"].fetch(ORACLE)

    assert [p.external_id for p in got] == ["0", "1", "2", "3", "4"]
    assert len(seen) == 3                          # 2 + 2 + 1, then stop
    finder = seen[0].url.params["finder"]
    assert finder.startswith("findReqs;") and "siteNumber=CX_1" in finder
    assert "locationId=42" in finder


def test_oracle_maps_a_requisition(monkeypatch):
    reqs = [requisition(7, secondaryLocations=[{"Name": "Chicago, IL, United States"}])]
    mock(monkeypatch, oracle_list(reqs))

    [p] = ADAPTERS["oracle"].fetch(ORACLE)

    assert p.employer == "Example Capital" and p.source == "oracle"
    assert p.url == ("https://example.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/"
                     "en/sites/CX_1/job/7")
    assert p.location == "New York, NY, United States; Chicago, IL, United States"
    assert p.posted_at == _dt.date(2026, 9, 1)
    assert p.deadline is None                      # the listing never carries one
    assert not p.hydrated                          # a one-line summary is not a description


def test_oracle_search_terms_are_quoted_keywords(monkeypatch):
    seen = mock(monkeypatch, oracle_list([requisition(1)]))
    ADAPTERS["oracle"].fetch({**ORACLE, "search": ["summer analyst"]})
    assert 'keyword="summer analyst"' in seen[0].url.params["finder"]


def test_oracle_hydration_fills_the_description_and_the_deadline(monkeypatch, eastern):
    def handler(request):
        assert request.url.path.endswith("/recruitingCEJobRequisitionDetails")
        assert 'Id="7"' in request.url.params["finder"]
        return httpx.Response(200, json={"items": [{
            "ExternalDescriptionStr": "<p>Rotate across three <strong>desks</strong>.</p>" * 20,
            "ExternalQualificationsStr": "<ul><li>Graduating 2027</li></ul>",
            "CorporateDescriptionStr": "<p>About the firm.</p>",
            "ExternalPostedStartDate": "2026-08-01T05:00:00+00:00",
            "ExternalPostedEndDate": "2026-10-01T03:55:00+00:00",
        }]})
    mock(monkeypatch, handler)
    posting = RawPosting(employer="Example Capital", title="Summer Analyst", url="u",
                         source="oracle", external_id="7")

    ADAPTERS["oracle"].hydrate(posting, ORACLE)

    assert posting.hydrated
    assert "<" not in posting.description
    assert "Graduating 2027" in posting.description
    assert posting.description.rstrip().endswith("About the firm.")   # boilerplate last
    assert posting.deadline == _dt.date(2026, 9, 30)
    assert posting.posted_at == _dt.date(2026, 8, 1)


def test_one_dropped_connection_does_not_lose_the_board(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _s: None)
    calls = {"n": 0}
    good = oracle_list([requisition(1)])

    def flaky(request):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectTimeout("dropped", request=request)
        return good(request)
    mock(monkeypatch, flaky)

    assert len(ADAPTERS["oracle"].fetch(ORACLE)) == 1
    assert calls["n"] == 2


def test_a_board_that_stays_down_is_a_source_error(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _s: None)

    def down(request):
        raise httpx.ConnectTimeout("down", request=request)
    mock(monkeypatch, down)

    with pytest.raises(SourceError, match="oracle/"):
        ADAPTERS["oracle"].fetch(ORACLE)


def test_an_http_error_is_an_answer_not_a_retry(monkeypatch):
    calls = {"n": 0}

    def forbidden(request):
        calls["n"] += 1
        return httpx.Response(403)
    mock(monkeypatch, forbidden)

    with pytest.raises(SourceError):
        ADAPTERS["oracle"].fetch(ORACLE)
    assert calls["n"] == 1


def test_resolve_recognises_an_oracle_careers_link():
    html = ('<a href="https://example.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/'
            'en/sites/CX_1/requisitions">Search jobs</a>')
    [found] = resolve.candidates(html)
    assert found.ats == "oracle" and found.supported
    assert found.config == {"host": "example.fa.us2.oraclecloud.com", "site": "CX_1"}
    assert "site: CX_1" in found.as_yaml("Example Capital")


# ------------------------------------------------------- embedded page data

PAGE = {"name": "Example Capital", "ats": "nextdata",
        "url": "https://careers.example.com/careers", "priority": 1}


def listing(n: int, title: str, **kw) -> dict:
    return {"data": {
        "id": n, "displayName": title, "jobUrl": f"{title.replace(' ', '-')}-{n}",
        "activeOnJobsListing": True, "validToDate": None,
        "department": {"name": "Quantitative Strategies"},
        "jobDescription": {
            "websiteDescription": "The firm seeks interns.&nbsp;Twelve weeks in New York.",
            "hhDescription": None,
            "responsibilitiesHtml": "<ul><li><p>Research a model.</p></li></ul>",
            "peopleWeAreLookingFor": ["Strong quantitative coursework."],
            "peopleWeAreLookingForHtml": None,
        },
        "jobMetadata": {"workStatus": "Intern", "jobSeekerCategoriesString": "Student",
                        "jobLocations": [{"name": "New York", "abbreviation": "NYC"}]},
        **kw,
    }}


def page_with(**props) -> str:
    blob = json.dumps({"props": {"pageProps": {"jobsFetchingError": False, **props}}})
    return (f'<html><body><div id="__next"></div><script id="__NEXT_DATA__" '
            f'type="application/json">{blob}</script></body></html>')


def test_page_listings_are_read_from_the_embedded_data():
    html = page_with(regularJobs=[listing(1, "Quantitative Analyst")],
                     internships=[listing(2, "Quantitative Analyst Intern")])

    got = pages.NextData().parse(html, PAGE)

    assert [p.title for p in got] == ["Quantitative Analyst", "Quantitative Analyst Intern"]
    intern = got[1]
    assert intern.url == "https://careers.example.com/careers/Quantitative-Analyst-Intern-2"
    assert intern.location == "New York"
    assert intern.source == "nextdata" and intern.external_id == "2"
    assert "Research a model." in intern.description
    assert "- Strong quantitative coursework." in intern.description
    assert "Intern · Quantitative Strategies · Student" in intern.description
    assert "&nbsp;" not in intern.description


def test_internal_postings_are_never_read_even_if_configured():
    html = page_with(regularJobs=[], internalJobs=[listing(9, "Employees Only Analyst")])
    got = pages.NextData().parse(html, {**PAGE, "lists": ["regularJobs", "internalJobs"]})
    assert got == []


def test_an_inactive_listing_is_skipped():
    html = page_with(regularJobs=[listing(1, "Analyst", activeOnJobsListing=False)],
                     internships=[])
    assert pages.NextData().parse(html, PAGE) == []


def test_a_renamed_list_fails_loudly():
    """A silent zero reads as a quiet week. A changed page must say so."""
    html = page_with(openRoles=[listing(1, "Analyst")])
    with pytest.raises(SourceError, match="no list 'regularJobs'"):
        pages.NextData().parse(html, PAGE)


@pytest.mark.parametrize("html,match", [
    ("<html>rendered elsewhere</html>", "no __NEXT_DATA__"),
    (page_with(jobsFetchingError=True, regularJobs=[], internships=[]), "could not load"),
])
def test_a_page_without_usable_data_is_a_source_error(html, match):
    with pytest.raises(SourceError, match=match):
        pages.NextData().parse(html, PAGE)


def test_page_postings_arrive_hydrated():
    html = page_with(regularJobs=[], internships=[listing(2, "Quantitative Analyst Intern")])
    [p] = pages.NextData().parse(html, PAGE)
    p.description = p.description * 3              # the live ones run to thousands
    assert p.hydrated


# ------------------------------------------------ the gates a live pass found


def nyc(title: str, body: str = "") -> RawPosting:
    return RawPosting(employer="Example Capital", title=title, url="u", source="test",
                      location="New York", description=body)


@pytest.mark.parametrize("title", [
    "Quantitative Analyst, Ph.D. Intern (New York) – Summer 2027",
    "PhD Quantitative Researcher",
    "MBA Summer Associate",
    "Postdoctoral Research Fellow",
])
def test_a_graduate_programme_title_is_rejected(title):
    verdict = score(nyc(title))
    assert verdict.verdict is Verdict.REJECT and verdict.rejected_by == "degree"


@pytest.mark.parametrize("title", [
    "Pre-Doctoral Research Assistant", "Predoctoral Fellow", "Pre doctoral RA",
])
def test_pre_doctoral_roles_are_for_undergraduates_and_pass(title):
    assert score(nyc(title)).rejected_by != "degree"


@pytest.mark.parametrize("title", [
    "Systems Engineering Intern (New York) - Summer 2027",
    "Software Developer Intern (New York) – Summer 2027",
    "Quant Systems: Systems Developer (New York)",
])
def test_engineering_titles_found_in_a_live_pass_are_rejected(title):
    assert score(nyc(title)).rejected_by == "technical"


def test_business_development_is_not_engineering():
    assert score(nyc("Business Development Associate")).rejected_by != "technical"


# ------------------------------------------------------ the hydration budget


class Thin:
    """A board whose listings carry titles only, like Oracle's and Workday's."""

    name = "greenhouse"

    def __init__(self, titles):
        self.titles = titles
        self.hydrated: list[str] = []

    def fetch(self, config):
        return [RawPosting(employer="Acme", title=t, url=f"https://x/{i}", source="greenhouse",
                           location="New York, NY", employer_priority=1)
                for i, t in enumerate(self.titles)]

    def hydrate(self, posting, config):
        self.hydrated.append(posting.title)
        posting.description = "Undergraduates graduating in 2027. " * 12
        return posting


REGISTRY = [{"name": "Acme", "ats": "greenhouse", "board": "acme", "priority": 1}]


def test_what_the_budget_misses_waits_instead_of_being_filed_thin(conn, monkeypatch):
    board = Thin(["Investment Analyst", "Credit Analyst", "Research Analyst"])
    monkeypatch.setitem(discover.ADAPTERS, "greenhouse", board)

    first = discover.run(conn, employers=REGISTRY, hydrate_limit=1)

    assert first.hydrated == 1 and first.deferred == 2
    assert len(first.created) == 1                 # nothing filed on its title alone

    second = discover.run(conn, employers=REGISTRY, hydrate_limit=10)

    assert second.already_known == 1 and second.deferred == 0
    assert len(second.created) == 2
    assert sorted(board.hydrated) == ["Credit Analyst", "Investment Analyst", "Research Analyst"]


def test_a_posting_the_budget_reached_is_filed_even_if_still_thin(conn, monkeypatch):
    """Deferral is for postings not tried. One that was tried and came back
    short is filed: waiting would not change it."""
    class Short(Thin):
        def hydrate(self, posting, config):
            self.hydrated.append(posting.title)
            return posting

    monkeypatch.setitem(discover.ADAPTERS, "greenhouse", Short(["Investment Analyst"]))
    result = discover.run(conn, employers=REGISTRY, hydrate_limit=5)
    assert result.deferred == 0 and len(result.created) == 1
