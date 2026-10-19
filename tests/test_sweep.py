"""apply sweep: is the posting still open where it was found?"""

from __future__ import annotations

import httpx
import pytest

from conftest import posting_from


def _client(handler):
    return lambda: httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


@pytest.mark.parametrize("status,body,expected", [
    (200, "<h1>Investment Intern</h1><p>Apply now</p>", "open"),
    (404, "not found", "closed"),
    (410, "gone", "closed"),
    (200, "<p>This job is no longer available.</p>", "closed"),
    (200, "<p>We are no longer accepting applications for this role.</p>", "closed"),
    (403, "forbidden", "unreachable"),
    (503, "busy", "unreachable"),
])
def test_what_the_source_says_decides_the_verdict(status, body, expected):
    from apply import sweep

    client = _client(lambda request: httpx.Response(status, text=body))
    assert sweep.check("https://boards.greenhouse.io/ashcombe/jobs/123", client=client).state == expected


def test_a_redirect_to_the_board_means_the_posting_is_gone():
    from apply import sweep

    def handler(request):
        if request.url.path.endswith("/123"):
            return httpx.Response(302, headers={"Location": "https://boards.greenhouse.io/ashcombe?error=true"})
        return httpx.Response(200, text="<h1>Open roles</h1>")

    result = sweep.check("https://boards.greenhouse.io/ashcombe/jobs/123", client=_client(handler))
    assert result.state == "closed" and "redirect" in result.reason


def test_a_timeout_is_unreachable_not_closed():
    from apply import sweep

    def handler(request):
        raise httpx.ConnectTimeout("slow")

    assert sweep.check("https://example.com/jobs/1", client=_client(handler)).state == "unreachable"


def _filed(conn, jd, **overrides):
    from apply import db

    posting = posting_from(jd, source_url="https://boards.greenhouse.io/x/jobs/1", **overrides)
    db.create_posting(conn, posting)
    return db.row_for(conn, posting.slug)


def test_a_sweep_logs_closed_postings_and_moves_no_status(conn, ashcombe_jd):
    from apply import db, digest, sweep

    row = _filed(conn, ashcombe_jd)
    report = sweep.run(conn, client=_client(lambda r: httpx.Response(404)))
    assert [r.posting.slug for r, _ in report.closed] == [row.posting.slug]
    assert db.row_for(conn, row.posting.slug).application.status == "draft"
    assert sweep.closed_at_source(conn, row.application.id)
    assert [r.posting.slug for r in digest.build(conn).closed] == [row.posting.slug]

    # Open again on the next sweep: the flag clears.
    sweep.run(conn, client=_client(lambda r: httpx.Response(200, text="Apply")))
    assert not sweep.closed_at_source(conn, row.application.id)
    assert digest.build(conn).closed == []


def test_a_dry_run_writes_nothing(conn, ashcombe_jd):
    from apply import db, sweep

    row = _filed(conn, ashcombe_jd)
    before = len(db.events(conn, row.application.id))
    sweep.run(conn, client=_client(lambda r: httpx.Response(404)), dry_run=True)
    assert len(db.events(conn, row.application.id)) == before


def test_submitted_and_urlless_postings_are_left_alone(conn, ashcombe_jd, quillon_jd):
    from apply import db, sweep
    from apply.models import Status

    sent = _filed(conn, ashcombe_jd)
    for target, via in ((Status.GENERATED, "gen"), (Status.READY, "review"),
                        (Status.SUBMITTED, "submit")):
        db.transition(conn, sent.application.id, target, via=via)
    db.create_posting(conn, posting_from(quillon_jd, source_url=None))
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(404)

    report = sweep.run(conn, client=_client(handler))
    assert seen == [] and report.checked == 0


def test_the_sweep_is_a_declared_sender():
    from apply.outbound import ALLOWED

    assert "apply.sweep" in ALLOWED


def test_show_says_a_posting_closed_at_the_source(conn, ashcombe_jd):
    from typer.testing import CliRunner

    from apply import sweep
    from apply.cli import app

    row = _filed(conn, ashcombe_jd)
    sweep.run(conn, client=_client(lambda r: httpx.Response(410)))
    result = CliRunner().invoke(app, ["show", row.posting.slug], env={"COLUMNS": "200"})
    assert "closed at the source" in result.output and "HTTP 410" in result.output


WD = ("https://blackrock.wd1.myworkdayjobs.com/en-US/BlackRock_Professional/job/"
      "New-York-NY/Associate_R265121")


@pytest.mark.parametrize("status,body,expected", [
    (200, '{"jobPostingInfo": {"title": "Associate"}}', "open"),
    (404, '{"errorCode": "S1"}', "closed"),
    (403, '{"errorCode": "S22", "message": "permission denied"}', "closed"),
    (403, "<html>blocked</html>", "unreachable"),
])
def test_a_workday_posting_is_asked_of_workdays_own_api(status, body, expected):
    """A Workday job page is a JavaScript shell that loads whether or not the job
    exists; the cxs API it renders from is the one that knows."""
    from apply import sweep

    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(status, text=body)

    assert sweep.check(WD, client=_client(handler)).state == expected
    assert seen == ["https://blackrock.wd1.myworkdayjobs.com/wday/cxs/blackrock/"
                    "BlackRock_Professional/job/New-York-NY/Associate_R265121"]
