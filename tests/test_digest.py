"""The digest and the four headline numbers."""

from __future__ import annotations

import datetime as _dt

import pytest

from apply import db, digest as digest_mod
from apply.models import Posting, Status


def _add(conn, slug, days_out=None, status=None):
    deadline = None if days_out is None else _dt.date.today() + _dt.timedelta(days=days_out)
    posting = db.create_posting(conn, Posting(
        slug=slug, company=slug.title(), role="Analyst", track="corporate",
        jd_raw="text", deadline=deadline))
    application = db.get_application(conn, posting.id)
    if status:
        db.transition(conn, application.id, Status.GENERATED, via="gen")
        if status in (Status.READY, Status.SUBMITTED):
            db.transition(conn, application.id, Status.READY, via="review")
        if status is Status.SUBMITTED:
            db.transition(conn, application.id, Status.SUBMITTED, via="submit")
    return application


def test_headline_counts(conn):
    _add(conn, "soon", days_out=3)
    _add(conn, "later", days_out=40)
    _add(conn, "undated")
    _add(conn, "reviewed", days_out=20, status=Status.READY)
    _add(conn, "sent", days_out=20, status=Status.SUBMITTED)

    counts = digest_mod.headline(conn)
    assert counts["due_7"] == 1
    assert counts["ready"] == 1
    assert counts["submitted_week"] == 1
    assert counts["no_deadline"] == 1
    assert counts["open"] == 5


def test_overdue_is_separate_from_upcoming(conn):
    _add(conn, "past", days_out=-2)
    _add(conn, "upcoming", days_out=5)
    result = digest_mod.build(conn)
    assert [r.posting.slug for r in result.overdue] == ["past"]
    assert [r.posting.slug for r in result.deadlines] == ["upcoming"]


def test_deadlines_past_the_horizon_are_still_listed(conn):
    """Not urgent is not the same as invisible."""
    _add(conn, "far", days_out=60)
    result = digest_mod.build(conn)
    assert not result.deadlines
    assert [r.posting.slug for r in result.beyond] == ["far"]


def test_undated_postings_are_flagged_not_guessed(conn):
    _add(conn, "undated")
    assert [r.posting.slug for r in digest_mod.build(conn).unverified] == ["undated"]


def test_a_submitted_application_is_not_chased_for_a_deadline(conn):
    _add(conn, "sent", days_out=2, status=Status.SUBMITTED)
    result = digest_mod.build(conn)
    assert not result.overdue
    assert [r.posting.slug for r in result.deadlines] == ["sent"]


def test_track_distribution_counts_only_open_work(conn):
    _add(conn, "one", days_out=5)
    _add(conn, "two", days_out=5)
    assert digest_mod.build(conn).tracks == {"corporate": 2}


def test_rows_sort_deadline_first_with_nulls_last(conn):
    _add(conn, "undated")
    _add(conn, "late", days_out=30)
    _add(conn, "early", days_out=1)
    assert [r.posting.slug for r in db.rows(conn)] == ["early", "late", "undated"]
