"""The relevance gate.

This is the only thing standing between a Workday employer's four hundred
openings and the API bill, so the hard rejects get the most tests. Calibration
is pinned against the two seed postings: both must clear the pursue bar, because
they are the shape of posting the whole system exists to catch.
"""

from __future__ import annotations

import pathlib

import pytest

from apply.score import Verdict, score
from apply.sources.base import RawPosting

FIXTURES = pathlib.Path(__file__).parents[1] / "data" / "examples"


def make(title="Investment Analyst", location="New York, NY", body="", priority=1):
    return RawPosting(employer="Test Co", title=title, url="https://x", source="test",
                      location=location, description=body, employer_priority=priority)


@pytest.mark.parametrize("title", [
    "Senior Analyst", "Sr. Research Analyst", "Vice President, Risk",
    "Director of Research", "Principal Economist", "Head of Trading",
    "Managing Director", "Portfolio Manager", "Staff Analyst",
])
def test_senior_titles_are_rejected(title):
    result = score(make(title=title))
    assert result.verdict is Verdict.REJECT
    assert result.rejected_by == "seniority"


@pytest.mark.parametrize("title", [
    "Software Engineer, Trading Systems", "Backend Engineer", "ML Engineer",
    "Site Reliability Engineer", "Data Engineer", "Hardware Engineer (FPGA/ASIC)",
    "Security Engineer", "Full Stack Developer",
])
def test_engineering_titles_are_rejected(title):
    """The line inside technology: analysing a business, yes; building the product, no."""
    result = score(make(title=title))
    assert result.verdict is Verdict.REJECT
    assert result.rejected_by == "technical"


@pytest.mark.parametrize("title", [
    "Workplace Services Rotational Coordinator", "Sales Analyst",
    "Technical Recruiter", "Marketing Associate",
])
def test_off_function_titles_are_rejected(title):
    assert score(make(title=title)).rejected_by == "function"


def test_a_title_can_trip_more_than_one_gate():
    """"Executive Assistant" is both off-function and senior-sounding. Which gate
    catches it first does not matter; that it is rejected does."""
    assert score(make(title="Executive Assistant")).verdict is Verdict.REJECT


@pytest.mark.parametrize("location", [
    "London, United Kingdom", "Hong Kong", "Mumbai, India", "Amsterdam, Netherlands",
])
def test_roles_outside_the_us_are_rejected(location):
    assert score(make(location=location)).rejected_by == "geography"


def test_experience_bars_are_rejected():
    result = score(make(body="We require 5+ years of relevant experience. " * 10))
    assert result.rejected_by == "experience"


def test_a_one_year_ask_is_not_a_bar():
    assert score(make(body="1+ years of experience preferred. " * 10)).verdict is not Verdict.REJECT


def test_required_advanced_degrees_are_rejected():
    assert score(make(body="A PhD is required for this role. " * 10)).rejected_by == "degree"


def test_both_seed_postings_clear_the_pursue_bar():
    """If either of these stops being `pursue`, the weights have drifted."""
    cases = [
        ("ashcombe.txt", "Investment Intern", "Hudson, New York"),
        ("quillon.txt", "2027 Full-Time Analyst Program (Americas)", "New York, NY"),
    ]
    for name, title, location in cases:
        body = (FIXTURES / name).read_text()
        result = score(make(title=title, location=location, body=body))
        assert result.verdict is Verdict.PURSUE, f"{name} fell to {result.value}"


def test_new_york_outweighs_everywhere_else():
    body = "Undergraduate students graduating in 2027. " * 12
    nyc = score(make(location="New York, NY", body=body)).value
    hub = score(make(location="Chicago, IL", body=body)).value
    assert nyc > hub


def test_an_unhydrated_posting_cannot_top_the_range():
    """The body is where the disqualifiers live, so a title-only score is capped."""
    result = score(make(title="Quantitative Research Analyst", body=""))
    assert result.value <= 79
    assert any("not hydrated" in r for r in result.reasons)


def test_every_rejection_explains_itself():
    result = score(make(title="Senior Vice President"))
    assert result.reasons and result.rejected_by


def test_thresholds_are_configurable():
    body = "Undergraduate students graduating in 2027. " * 12
    posting = make(title="Business Analyst", body=body)
    assert score(posting, {"thresholds": {"pursue": 10, "maybe": 5}}).verdict is Verdict.PURSUE
    assert score(posting, {"thresholds": {"pursue": 99, "maybe": 98}}).verdict is Verdict.REJECT


# ------------------------------------------------------------- class year

@pytest.mark.parametrize("title", [
    "2027 Summer Intern - Research Group - Sophomore Intern",
    "Sophomore Summer Analyst Program",
    "Freshman Insight Programme",
])
def test_roles_scoped_to_another_class_year_are_rejected(title):
    """One employer can run a dozen separate sophomore programmes."""
    result = score(make(title=title), standing="senior")
    assert result.verdict is Verdict.REJECT
    assert result.rejected_by == "class year"


def test_a_rising_senior_is_a_student_not_a_job_level():
    """"Rising Senior Summer Analyst" used to trip the seniority gate."""
    result = score(make(title="Rising Senior Summer Analyst",
                        body="Graduating in 2027. " * 20), standing="senior")
    assert result.verdict is not Verdict.REJECT


def test_junior_or_senior_year_wording_is_not_a_job_level():
    result = score(make(title="Summer Analyst",
                        body="Open to students in their junior or senior year. " * 10),
                   standing="senior")
    assert result.verdict is not Verdict.REJECT


def test_a_senior_job_title_is_still_rejected():
    assert score(make(title="Senior Risk Analyst"), standing="senior").rejected_by == "seniority"


def test_without_a_standing_the_class_gate_does_not_fire():
    """Callers that do not know the owner's year should not guess one."""
    assert score(make(title="Sophomore Summer Analyst")).rejected_by != "class year"
