"""Source adapters. Offline: no test here touches the network.

Live behaviour was verified by hand against one real board of each kind: a
Greenhouse listing a few hundred postings long, and a Workday board whose
hydration carries deadlines. What these tests protect is the parsing and
identity logic underneath.
"""

from __future__ import annotations

import datetime as _dt

import pytest

from apply.sources.base import RawPosting, parse_date, parse_relative, strip_html


def make(**kw) -> RawPosting:
    base = dict(employer="Acme", title="Analyst", url="https://x", source="test")
    return RawPosting(**{**base, **kw})


def test_strip_html_handles_escaped_markup():
    """Greenhouse returns its content HTML-escaped; stripping tags first is a no-op."""
    assert "About" in strip_html("&lt;h3&gt;About&lt;/h3&gt;&lt;p&gt;Text&lt;/p&gt;")
    assert "<" not in strip_html("&lt;h3&gt;About&lt;/h3&gt;")


def test_strip_html_drops_scripts_and_keeps_structure():
    text = strip_html("<p>One</p><script>evil()</script><ul><li>Two</li></ul>")
    assert "evil" not in text
    assert "One" in text and "Two" in text


def test_strip_html_survives_empty():
    assert strip_html("") == ""


@pytest.mark.parametrize("value,expected", [
    ("2026-09-17T16:01:57-04:00", _dt.date(2026, 9, 17)),
    ("2026-09-17", _dt.date(2026, 9, 17)),
    ("", None),
    (None, None),
    ("not a date", None),
])
def test_parse_date(value, expected):
    assert parse_date(value) == expected


def test_relative_dates_that_are_buckets_stay_none():
    """Workday's "Posted 30+ Days Ago" is a bucket, not a date."""
    assert parse_relative("Posted 30+ Days Ago") is None
    assert parse_relative("Posted 3 Days Ago") == _dt.date.today() - _dt.timedelta(days=3)
    assert parse_relative("Posted Today") == _dt.date.today()


def test_the_same_role_from_two_sources_collapses():
    """Greenhouse and Workday write the same desk two different ways."""
    a = make(location="New York, New York, United States", source="greenhouse")
    b = make(location="NY7 - 50 Hudson Yards, New York", source="workday")
    assert a.fingerprint == b.fingerprint


def test_word_order_and_punctuation_do_not_change_identity():
    assert make(title="Analyst, Risk").fingerprint == make(title="Risk Analyst").fingerprint


def test_parenthetical_decoration_is_ignored():
    """"(Remote)" and "(AMRS)" are labels on a role, not different roles."""
    assert make(title="Risk Analyst (Remote)").fingerprint == \
           make(title="Risk Analyst").fingerprint


def test_different_cities_are_different_postings():
    assert make(location="New York, NY").fingerprint != make(location="London, UK").fingerprint


def test_different_employers_are_different_postings():
    assert make(employer="Acme").fingerprint != make(employer="Beta").fingerprint


def test_hydrated_requires_a_real_description():
    assert not make(description="").hydrated
    assert not make(description="short").hydrated
    assert make(description="x" * 300).hydrated


def test_the_user_agent_identifies_the_software_not_a_person():
    """A clone polls job boards as itself, never as this repository's author.

    The string a board operator sees has to be honest about what is calling —
    so it names the tool and the traffic — and has to stay free of whoever
    happens to be running it: a name, a handle, a profile URL or an email.
    """
    import re

    from apply.sources.ats import HEADERS, USER_AGENT

    assert HEADERS["User-Agent"] == USER_AGENT
    assert USER_AGENT.startswith("apply/")
    assert "personal job-application tracker" in USER_AGENT
    assert not re.search(r"github\.com|@|linkedin|mailto:", USER_AGENT, re.I)
