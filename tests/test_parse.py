"""Extraction. The deadline tests matter most: a wrong deadline is worse than
no deadline, so the parser is required to give up rather than guess."""

from __future__ import annotations

import datetime as _dt

import pytest

from apply.parse import find_comp, find_deadline, find_location, parse


@pytest.mark.parametrize("text,expected", [
    ("Application deadline: October 14, 2026", _dt.date(2026, 10, 14)),
    ("Apply by 14 October 2026", _dt.date(2026, 10, 14)),
    ("Deadline: 2026-10-14", _dt.date(2026, 10, 14)),
    ("Applications close 10/14/2026", _dt.date(2026, 10, 14)),
    ("Applications are due October 14th, 2026.", _dt.date(2026, 10, 14)),
    ("Last day to apply: Oct 14, 2026", _dt.date(2026, 10, 14)),
])
def test_reads_a_stated_deadline(text, expected):
    assert find_deadline(text)[0] == expected


def test_never_guesses_a_year():
    deadline, notes = find_deadline("Apply by October 14 for the analyst program.")
    assert deadline is None
    assert any("no year" in n for n in notes)


def test_no_deadline_is_none_not_a_guess():
    deadline, notes = find_deadline("We review applications on a rolling basis.")
    assert deadline is None
    assert notes


def test_a_start_date_is_not_a_deadline():
    text = "Program begins June 1, 2027. We review applications on a rolling basis."
    assert find_deadline(text)[0] is None


def test_prefers_the_deadline_over_a_start_date():
    text = "Application deadline: October 14, 2026.\nProgram begins July 6, 2027."
    assert find_deadline(text)[0] == _dt.date(2026, 10, 14)


@pytest.mark.parametrize("text,expected", [
    ("Pay: $20/hr", "$20/hr"),
    ("Compensation: $110,000 base salary", "$110,000"),
    ("$20-30/hr depending on experience", "$20-30/hr"),
    ("Salary: $110K", "$110K"),
])
def test_reads_comp(text, expected):
    assert find_comp(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("Location: Chicago, IL", "Chicago, IL"),
    ("Analyst\nAcme LP\nNew York, NY", "New York, NY"),
    ("Analyst\nAcme LP\nRichmond, Virginia", "Richmond, Virginia"),
])
def test_reads_location(text, expected):
    assert find_location(text) == expected


@pytest.mark.parametrize("text,company,role", [
    ("Company: Acme Capital\nJob Title: Investment Analyst", "Acme Capital", "Investment Analyst"),
    ("Jane Street — Quantitative Trader Intern", "Jane Street", "Quantitative Trader Intern"),
    ("Summer Analyst at Beacon Partners", "Beacon Partners", "Summer Analyst"),
    ("Investment Intern\nVCIMCO\nRichmond, Virginia", "VCIMCO", "Investment Intern"),
    ("Analyst\nJPMorgan\nNYC", "JPMorgan", "Analyst"),
    ("Software Intern\neBay\nSan Jose, CA", "eBay", "Software Intern"),
])
def test_reads_company_and_role(text, company, role):
    parsed = parse(text)
    assert (parsed.company, parsed.role) == (company, role)


def test_keeps_a_trailing_period_in_a_company_name():
    assert parse("Company: Smith & Co.\nJob Title: Analyst").company == "Smith & Co."


def test_jd_raw_is_kept_verbatim(blackrock_jd):
    assert parse(blackrock_jd).jd_raw == blackrock_jd


def test_incomplete_parse_refuses_to_make_a_posting():
    parsed = parse("Rolling applications accepted.")
    assert not parsed.complete
    with pytest.raises(ValueError):
        parsed.to_posting()
