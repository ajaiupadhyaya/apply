"""Job-alert email parsing.

The fixtures are invented mail — no firm in them exists and no inbox they came
from — written to the layout Handshake's round-up and "about to close" alerts
use: employer and role on consecutive lines, a blank line, then a bullet-
separated line of pay, job type and location. Handshake will change that layout
eventually; when it does, `is_job_email` will keep returning True and
`parse_alert` will start returning nothing, so the count assertions below are
the canary.
"""

from __future__ import annotations

import datetime as _dt
import pathlib

import pytest

from apply import db, discover
from apply.score import Verdict, score
from apply.sources.alerts import find_deadline, is_job_email, parse_alert

ALERTS = pathlib.Path(__file__).parent / "fixtures" / "alerts"
HANDSHAKE = "handshake@notifications.joinhandshake.com"


def load(name: str) -> str:
    return (ALERTS / name).read_text()


# ------------------------------------------------------- which mail matters

@pytest.mark.parametrize("subject", [
    "Rae, Fenwold Securities sees you as a top applicant for ... and more",
    '"Search on 8/29/2026": Vantress - Software Engineering Intern and more',
    "Your saved job at Calderwell Advisors is about to close",
    "New items from Fenwold Securities and more added to collections you follow",
    "Flexible jobs near you this week",
])
def test_job_bearing_subjects_are_recognised(subject):
    assert is_job_email(subject, HANDSHAKE)


@pytest.mark.parametrize("subject", [
    "Application sent to Example Partners — here's what's next",
    "Reminder: Upcoming Appointment",
    "You have a new notification on Handshake",
    "Reactivation Request Approved",
    "Handshake School Registration Information",
    "Apply Your Skills in Project Management!",
])
def test_handshake_noise_is_skipped(subject):
    """Handshake sends far more mail than it sends jobs."""
    assert not is_job_email(subject, HANDSHAKE)


def test_mail_from_elsewhere_is_ignored():
    assert not is_job_email("Your weekly jobs round-up", "newsletter@example.com")


# -------------------------------------------------------------- extraction

def test_a_round_up_yields_every_listing():
    postings = parse_alert("round-up", load("roundup.txt"), _dt.date(2026, 9, 18))
    assert len(postings) == 5
    first = postings[0]
    assert first.employer == "Fenwold Securities"
    assert first.title.startswith("Fenwold Graduate Program")
    assert first.location == "New York City, NY"


def test_sponsored_rows_are_read_like_any_other():
    postings = parse_alert("round-up", load("roundup.txt"), _dt.date(2026, 9, 18))
    promoted = next(p for p in postings if p.employer.startswith("Harrowgate"))
    assert promoted.title == "Operations Coordinator"


def test_location_decoration_is_stripped():
    postings = parse_alert("round-up", load("roundup.txt"), _dt.date(2026, 9, 18))
    decorated = next(p for p in postings if "Brindlemere" in p.employer)
    assert decorated.location == "Hartford, CT"         # from "Hartford, CT +3 (Hybrid)"


def test_alerts_carry_no_description():
    """Which is why nothing from this channel can reach `pursue` on a title alone."""
    for posting in parse_alert("round-up", load("roundup.txt"), _dt.date(2026, 9, 18)):
        assert not posting.hydrated
        assert posting.source == "alert"


def test_an_empty_body_yields_nothing():
    assert parse_alert("round-up", "", _dt.date(2026, 9, 18)) == []


# ---------------------------------------------------------------- deadline

def test_a_closing_alert_carries_its_deadline():
    postings = parse_alert("about to close", load("closing.txt"), _dt.date(2026, 9, 20))
    assert len(postings) == 1
    assert postings[0].deadline == _dt.date(2026, 9, 24)


def test_the_year_comes_from_the_email_not_from_a_guess():
    """"due Thu, Sep 24" in a message sent 20 September is unambiguous."""
    assert find_deadline("due Thu, Sep 24 12:59 am EDT", _dt.date(2026, 9, 20)) \
        == _dt.date(2026, 9, 24)
    # A January deadline in a December email belongs to the following year.
    assert find_deadline("applications are due Jan 15", _dt.date(2026, 12, 10)) \
        == _dt.date(2027, 1, 15)


def test_no_due_date_stays_none():
    assert find_deadline("Come work with us!", _dt.date(2026, 9, 20)) is None


def test_a_round_up_does_not_inherit_one_posting_s_deadline():
    postings = parse_alert("round-up", load("roundup.txt"), _dt.date(2026, 9, 18))
    assert all(p.deadline is None for p in postings)


# ------------------------------------------------------------- end to end

def test_ingestion_files_the_relevant_and_drops_the_rest(conn):
    messages = [
        discover.Message(subject="Rae, Fenwold Securities sees you as a top applicant",
                         body=load("roundup.txt"), received=_dt.date(2026, 9, 18),
                         sender=HANDSHAKE),
        discover.Message(subject="Reminder: Upcoming Appointment",
                         body="You have an appointment.", received=_dt.date(2026, 9, 20),
                         sender=HANDSHAKE),
    ]
    result = discover.ingest_alerts(conn, messages)
    assert result.fetched == 1                    # the appointment was not parsed
    assert result.unique == 5
    assert result.rejected >= 3                   # the coordinator and the district manager
    filed = {db.get_posting(conn, slug).company for slug in result.created}
    assert "Fenwold Securities" in filed
    assert "Fairwick Grocers" not in filed


def test_ingested_postings_dedupe_against_the_registry(conn):
    message = discover.Message(subject="Rae, Fenwold Securities sees you as a top applicant",
                               body=load("roundup.txt"),
                               received=_dt.date(2026, 9, 18), sender=HANDSHAKE)
    first = discover.ingest_alerts(conn, [message])
    second = discover.ingest_alerts(conn, [message])
    assert first.created and not second.created
    # Only what was filed has a fingerprint to recognise. The rejects are scored
    # again on every pass, which is free and keeps the gate stateless.
    assert second.already_known == len(first.created)
    assert second.rejected == first.rejected


def test_a_2027_graduate_programme_in_new_york_survives_the_gate():
    """The case that exposed the scorer being overfit to ATS-style titles."""
    postings = parse_alert("round-up", load("roundup.txt"), _dt.date(2026, 9, 18))
    bank = next(p for p in postings if p.employer == "Fenwold Securities")
    assert score(bank).verdict is not Verdict.REJECT
