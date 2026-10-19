"""The Eightfold adapter: the API a talent-marketplace careers page renders from.

Offline: every request goes to an httpx.MockTransport. The shapes below are
trimmed from what one live board returned on 2026-09-22, with names replaced.
"""

from __future__ import annotations

import datetime as _dt

import httpx
import pytest

from apply.sources import ADAPTERS, eightfold
from apply.sources.base import SourceError

from test_boards import mock

BOARD = {"name": "Example Capital", "ats": "eightfold", "host": "example.eightfold.ai",
         "domain": "example.com", "max_results": 100, "priority": 1}


def position(n: int, **kw) -> dict:
    return {"id": 75590000 + n, "name": f"Quantitative Analyst {n}",
            "posting_name": f"Quantitative Analyst {n}",
            "location": "New York, New York, United States of America",
            "locations": ["New York, New York, United States of America"],
            "department": "Research", "business_unit": "Equities",
            "t_create": 1758326400,          # 2025-09-20, UTC
            "ats_job_id": f"REQ-{n}", "display_job_id": f"REQ-{n}",
            "canonicalPositionUrl": f"https://example.eightfold.ai/careers/job/{75590000 + n}",
            "job_description": "", "isPrivate": False, **kw}


def board(all_positions: list[dict], detail: dict | None = None):
    """The list endpoint, paginated the way the live one is, plus job detail."""
    def handler(request: httpx.Request) -> httpx.Response:
        if "/jobs/" in request.url.path:
            job_id = int(request.url.path.rsplit("/", 1)[1])
            found = next((p for p in all_positions if p["id"] == job_id), None)
            if found is None:
                return httpx.Response(404, json={})
            return httpx.Response(200, json={**found, **(detail or {})})
        start = int(request.url.params.get("start", 0))
        num = int(request.url.params.get("num", 10))
        query = (request.url.params.get("query") or "").lower()
        matching = [p for p in all_positions if query in p["name"].lower()]
        return httpx.Response(200, json={"count": len(matching),
                                         "positions": matching[start:start + num]})
    return handler


def test_the_whole_board_is_paged_through(monkeypatch):
    monkeypatch.setattr(eightfold.Eightfold, "PAGE", 2)
    seen = mock(monkeypatch, board([position(n) for n in range(5)]))

    got = ADAPTERS["eightfold"].fetch(BOARD)

    assert [p.external_id for p in got] == [str(75590000 + n) for n in range(5)]
    assert len(seen) == 3                              # 2 + 2 + 1, then the count stops it
    assert seen[0].url.params["domain"] == "example.com"


def test_no_more_than_max_results_are_asked_for(monkeypatch):
    monkeypatch.setattr(eightfold.Eightfold, "PAGE", 10)
    seen = mock(monkeypatch, board([position(n) for n in range(60)]))

    got = ADAPTERS["eightfold"].fetch({**BOARD, "max_results": 25})

    assert len(got) == 25
    assert int(seen[-1].url.params["num"]) == 5        # the last page is trimmed to the cap


def test_a_position_is_mapped(monkeypatch):
    mock(monkeypatch, board([position(1, locations=[
        "New York, New York, United States of America", "Miami, Florida, United States"])]))

    [got] = ADAPTERS["eightfold"].fetch(BOARD)

    assert got.title == "Quantitative Analyst 1"
    assert got.url == "https://example.eightfold.ai/careers/job/75590001"
    assert got.source == "eightfold" and got.external_id == "75590001"
    assert got.location == "New York, New York, United States of America; Miami, Florida, United States"
    assert got.posted_at == _dt.date(2025, 9, 20)
    assert got.employer == "Example Capital" and got.employer_priority == 1
    assert not got.hydrated              # the listing carries no description


def test_search_terms_are_separate_queries_and_the_results_are_deduplicated(monkeypatch):
    postings = [position(1, name="Quantitative Analyst"), position(2, name="Credit Analyst"),
                position(3, name="Compliance Manager")]
    seen = mock(monkeypatch, board(postings))

    got = ADAPTERS["eightfold"].fetch({**BOARD, "search": ["analyst", "credit"]})

    assert sorted(p.title for p in got) == ["Credit Analyst", "Quantitative Analyst"]
    assert {r.url.params.get("query") for r in seen} == {"analyst", "credit"}


def test_a_private_posting_is_not_read(monkeypatch):
    """isPrivate is a req the board does not show publicly."""
    mock(monkeypatch, board([position(1), position(2, isPrivate=True)]))

    got = ADAPTERS["eightfold"].fetch(BOARD)

    assert [p.external_id for p in got] == ["75590001"]


def test_hydration_fills_the_description(monkeypatch):
    postings = [position(1)]
    mock(monkeypatch, board(postings, detail={
        "job_description": "<p><b>Overview:</b></p><p>The desk trades equities.</p>"}))
    [got] = ADAPTERS["eightfold"].fetch(BOARD)

    filled = ADAPTERS["eightfold"].hydrate(got, BOARD)

    assert "Overview:" in filled.description and "The desk trades equities." in filled.description
    assert "<p>" not in filled.description


def test_a_board_that_does_not_answer_is_a_source_error(monkeypatch):
    def down(request):
        return httpx.Response(500)
    mock(monkeypatch, down)

    with pytest.raises(SourceError, match="eightfold/example.eightfold.ai"):
        ADAPTERS["eightfold"].fetch(BOARD)


def test_a_hydration_that_fails_is_a_source_error(monkeypatch):
    mock(monkeypatch, board([position(1)]))
    [got] = ADAPTERS["eightfold"].fetch(BOARD)
    got.external_id = "404404"                          # a req withdrawn between passes

    with pytest.raises(SourceError, match="eightfold hydrate"):
        ADAPTERS["eightfold"].hydrate(got, BOARD)


def test_resolve_recognises_an_eightfold_careers_link():
    from apply import resolve

    html = ('<script src="https://static.eightfold.ai/bundle.js"></script>'
            '<a href="https://example.eightfold.ai/careers?query=analyst">Search jobs</a>')
    [found] = resolve.candidates(html)

    assert found.ats == "eightfold" and found.supported
    assert found.config == {"host": "example.eightfold.ai"}
    assert "host: example.eightfold.ai" in found.as_yaml("Example Capital")
