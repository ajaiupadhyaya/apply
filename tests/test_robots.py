"""A careers page is read only where the site's robots.txt allows it (RFC 9309)."""

from __future__ import annotations

import httpx
import pytest

PAGE = "https://careers.example.com/jobs"


def _client(robots_status=200, robots_body="", page_body="<html></html>", seen=None):
    def handler(request):
        if seen is not None:
            seen.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(robots_status, text=robots_body)
        return httpx.Response(200, text=page_body)

    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("status,body,allowed", [
    (200, "User-agent: *\nDisallow: /jobs\n", False),
    (200, "User-agent: *\nDisallow: /private\n", True),
    (200, "User-agent: apply\nDisallow: /\n", False),
    (404, "", True),                 # no robots.txt: everything is allowed
    (503, "", False),                # unreachable: assume nothing is
])
def test_robots_decides(status, body, allowed):
    from apply.sources.pages import robots_allows

    ok, why = robots_allows(_client(status, body), PAGE, "apply/1.0 (tracker)")
    assert ok is allowed
    if not ok:
        assert "robots.txt" in why


def test_the_page_adapter_refuses_a_disallowed_page(monkeypatch):
    from apply.sources import ats, pages
    from apply.sources.base import SourceError

    seen: list[str] = []
    monkeypatch.setattr(ats, "_client",
                        lambda: _client(200, "User-agent: *\nDisallow: /\n", seen=seen))
    with pytest.raises(SourceError, match="robots.txt"):
        pages.NextData().fetch({"url": PAGE})
    assert seen == ["/robots.txt"]             # the page itself was never requested


def test_resolve_refuses_a_disallowed_page(monkeypatch):
    from apply import resolve

    monkeypatch.setattr(resolve, "_http", lambda: _client(200, "User-agent: *\nDisallow: /\n"))
    with pytest.raises(PermissionError, match="robots.txt"):
        resolve.fetch(PAGE)


def test_resolve_reads_an_allowed_page(monkeypatch):
    from apply import resolve

    monkeypatch.setattr(resolve, "_http", lambda: _client(404, page_body="<p>jobs</p>"))
    assert resolve.fetch(PAGE) == "<p>jobs</p>"
