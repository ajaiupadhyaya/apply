"""no_response: the outcome most applications actually have."""

from __future__ import annotations

import datetime as _dt

import pytest

from conftest import posting_from


def _submitted(conn, posting, *, days_ago: int = 0):
    from apply import db
    from apply.models import Status

    db.create_posting(conn, posting)
    row = db.row_for(conn, posting.slug)
    for target, via in ((Status.GENERATED, "gen"), (Status.READY, "review"),
                        (Status.SUBMITTED, "submit")):
        db.transition(conn, row.application.id, target, via=via)
    if days_ago:
        when = (_dt.datetime.now() - _dt.timedelta(days=days_ago)).isoformat(sep=" ")
        with conn:
            conn.execute("UPDATE application SET submitted_at = ? WHERE id = ?",
                         (when, row.application.id))
    return db.row_for(conn, posting.slug)


def test_a_submitted_application_can_close_with_no_response(conn, ashcombe_jd):
    from apply import db
    from apply.models import Status

    row = _submitted(conn, posting_from(ashcombe_jd))
    db.transition(conn, row.application.id, Status.NO_RESPONSE, via="mark")
    assert db.row_for(conn, row.posting.slug).application.status == "no_response"
    assert any(e.kind == "no_response" for e in db.events(conn, row.application.id))


def test_no_response_needs_something_to_have_been_sent(conn, ashcombe_jd):
    from apply import db
    from apply.models import Status, TransitionError

    posting = posting_from(ashcombe_jd)
    db.create_posting(conn, posting)
    row = db.row_for(conn, posting.slug)
    with pytest.raises(TransitionError):
        db.transition(conn, row.application.id, Status.NO_RESPONSE, via="mark")


def test_no_response_is_closed(conn, ashcombe_jd):
    from apply import db
    from apply.models import Status, TransitionError

    row = _submitted(conn, posting_from(ashcombe_jd))
    db.transition(conn, row.application.id, Status.NO_RESPONSE, via="mark")
    with pytest.raises(TransitionError):
        db.transition(conn, row.application.id, Status.WITHDRAWN, via="mark")


def test_a_late_reply_still_lands(conn, ashcombe_jd):
    """Firms answer after months. A ghosted application that calls back is not stuck."""
    from apply import db
    from apply.models import Status

    row = _submitted(conn, posting_from(ashcombe_jd))
    db.transition(conn, row.application.id, Status.NO_RESPONSE, via="mark")
    db.transition(conn, row.application.id, Status.INTERVIEWING, via="mark")
    assert db.row_for(conn, row.posting.slug).application.status == "interviewing"


def test_the_digest_suggests_it_after_sixty_quiet_days(conn, ashcombe_jd, quillon_jd):
    from apply import digest

    old = _submitted(conn, posting_from(ashcombe_jd), days_ago=61)
    recent = _submitted(conn, posting_from(quillon_jd), days_ago=20)
    d = digest.build(conn)
    assert [r.posting.slug for r in d.ghosted] == [old.posting.slug]
    assert [r.posting.slug for r in d.silent] == [recent.posting.slug]


def test_status_and_the_dashboard_hide_it_like_any_closed_row(conn, ashcombe_jd):
    from typer.testing import CliRunner

    from apply import db
    from apply.cli import app
    from apply.models import Status
    from apply.web import routes

    row = _submitted(conn, posting_from(ashcombe_jd))
    result = CliRunner().invoke(app, ["mark", row.posting.slug, "no_response"])
    assert result.exit_code == 0, result.output
    assert db.row_for(conn, row.posting.slug).application.status == Status.NO_RESPONSE.value
    listing = CliRunner().invoke(app, ["status"], env={"COLUMNS": "200"})
    assert row.posting.company not in listing.output
    assert "no_response" in routes.MARKABLE
