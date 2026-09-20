"""The status column. This is the safety mechanism, so it gets the most tests.

Two invariants: nothing reaches `ready` except a `review` action, and nothing
reaches `submitted` except a `submit` action.
"""

from __future__ import annotations

import pytest

from apply import db
from apply.models import Posting, Status, TransitionError, check_transition


@pytest.fixture
def application(conn):
    posting = db.create_posting(conn, Posting(
        slug="acme-analyst-2027", company="Acme", role="Analyst",
        track="corporate", jd_raw="text",
    ))
    return db.get_application(conn, posting.id)


def test_a_new_posting_starts_as_a_draft(application):
    assert application.status == Status.DRAFT.value


def test_the_creation_is_logged(conn, application):
    assert [e.kind for e in db.events(conn, application.id)] == ["created"]


def test_generated_cannot_jump_to_submitted(conn, application):
    db.transition(conn, application.id, Status.GENERATED, via="gen")
    with pytest.raises(TransitionError, match="has not been read"):
        db.transition(conn, application.id, Status.SUBMITTED, via="submit")


def test_only_the_review_action_can_write_ready(conn, application):
    db.transition(conn, application.id, Status.GENERATED, via="gen")
    for imposter in ("gen", "submit", "mark", "web", ""):
        with pytest.raises(TransitionError, match="human-only"):
            db.transition(conn, application.id, Status.READY, via=imposter)
    db.transition(conn, application.id, Status.READY, via="review")
    assert db.get_application_by_id(conn, application.id).status == Status.READY.value


def test_only_the_submit_action_can_write_submitted(conn, application):
    db.transition(conn, application.id, Status.GENERATED, via="gen")
    db.transition(conn, application.id, Status.READY, via="review")
    for imposter in ("gen", "review", "mark"):
        with pytest.raises(TransitionError, match="human-only"):
            db.transition(conn, application.id, Status.SUBMITTED, via=imposter)


def test_review_stamps_reviewed_at(conn, application):
    db.transition(conn, application.id, Status.GENERATED, via="gen")
    db.transition(conn, application.id, Status.READY, via="review")
    assert db.get_application_by_id(conn, application.id).reviewed_at


def test_submit_stamps_submitted_at_and_nothing_else_does(conn, application):
    db.transition(conn, application.id, Status.GENERATED, via="gen")
    db.transition(conn, application.id, Status.READY, via="review")
    assert db.get_application_by_id(conn, application.id).submitted_at is None
    db.transition(conn, application.id, Status.SUBMITTED, via="submit")
    assert db.get_application_by_id(conn, application.id).submitted_at


def test_regenerating_clears_the_review(conn, application):
    db.transition(conn, application.id, Status.GENERATED, via="gen")
    db.transition(conn, application.id, Status.READY, via="review")
    db.transition(conn, application.id, Status.GENERATED, via="gen")
    after = db.get_application_by_id(conn, application.id)
    assert after.status == Status.GENERATED.value
    assert after.reviewed_at is None


def test_every_transition_writes_an_event(conn, application):
    db.transition(conn, application.id, Status.GENERATED, via="gen")
    db.transition(conn, application.id, Status.READY, via="review")
    db.transition(conn, application.id, Status.SUBMITTED, via="submit")
    kinds = [e.kind for e in db.events(conn, application.id)]
    assert set(kinds) == {"created", "generated", "reviewed", "submitted"}


def test_withdrawn_is_reachable_from_anywhere(conn, application):
    db.transition(conn, application.id, Status.WITHDRAWN, via="mark")
    assert db.get_application_by_id(conn, application.id).status == Status.WITHDRAWN.value


def test_a_terminal_state_stays_terminal(conn, application):
    db.transition(conn, application.id, Status.WITHDRAWN, via="mark")
    with pytest.raises(TransitionError):
        db.transition(conn, application.id, Status.GENERATED, via="gen")


def test_post_submission_outcomes(conn, application):
    db.transition(conn, application.id, Status.GENERATED, via="gen")
    db.transition(conn, application.id, Status.READY, via="review")
    db.transition(conn, application.id, Status.SUBMITTED, via="submit")
    db.transition(conn, application.id, Status.ACKNOWLEDGED, via="mark")
    db.transition(conn, application.id, Status.ASSESSMENT, via="mark")
    db.transition(conn, application.id, Status.INTERVIEWING, via="mark")
    db.transition(conn, application.id, Status.OFFER, via="mark")
    assert db.get_application_by_id(conn, application.id).status == Status.OFFER.value


def test_check_transition_is_pure():
    """The guard is callable without a database, so callers can ask before acting."""
    check_transition(Status.READY, Status.SUBMITTED, "submit")
    with pytest.raises(TransitionError):
        check_transition(Status.GENERATED, Status.SUBMITTED, "submit")
