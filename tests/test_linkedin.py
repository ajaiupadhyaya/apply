"""LinkedIn job-alert mail.

The fixture is invented mail: no firm in it exists, the job ids are made up,
and there is no inbox behind it. What it reproduces exactly is the card layout
LinkedIn's digests use, because that is what the parser anchors on — including
the tracking query string, whose `otpToken` is a one-time sign-in token and the
reason every stored URL is cut back to its bare /jobs/view/<id>/ form.
"""

from __future__ import annotations

import datetime as _dt
import pathlib

import pytest

from apply import db, discover
from apply.discover import Aliases
from apply.score import score
from apply.sources.alerts import (
    clean_linkedin_url, is_job_email, parse_alert, parse_linkedin, source_of,
)
from apply.sources.base import RawPosting

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "alerts" / "linkedin_digest.txt"
SENT = _dt.date(2026, 3, 20)
LI = "jobs-listings@linkedin.com"


def cards():
    return parse_linkedin(FIXTURE.read_text(), SENT)


# ------------------------------------------------------------- which mail

@pytest.mark.parametrize("sender", [
    "jobalerts-noreply@linkedin.com", "jobs-listings@linkedin.com",
    "LinkedIn Job Alerts <jobalerts-noreply@linkedin.com>",
])
def test_job_senders_are_read(sender):
    assert source_of(sender) == "linkedin" and is_job_email("x", sender)


@pytest.mark.parametrize("sender", [
    "messages-noreply@linkedin.com",          # connection suggestions
    "notifications-noreply@linkedin.com",     # "3 searches included you"
    "editors-noreply@linkedin.com",           # newsletters
    "linkedin@e.linkedin.com",                # marketing
])
def test_the_rest_of_linkedin_s_mail_is_ignored(sender):
    assert not is_job_email("x", sender)


def test_a_new_sender_address_is_still_recognised_by_its_cards():
    """Addresses change; a card with a /jobs/view/ link does not look like anything else."""
    body = FIXTURE.read_text()
    assert source_of("some-new-address@linkedin.com", body) == "linkedin"


# ------------------------------------------------------------ extraction

def test_every_card_is_read():
    assert len(cards()) == 6


def test_title_company_and_location_come_from_the_top_of_the_card():
    markets = cards()[0]
    assert markets.title == ("2027 Summer Analyst Program - Global Markets "
                             "(Sales and Trading)")
    assert markets.employer == "Fenwold Securities"
    assert markets.location == "New York"
    assert markets.source == "linkedin"


def test_insight_lines_never_become_the_location():
    for card in cards():
        assert card.location and "apply" not in card.location.lower()
        assert "hiring" not in card.location.lower()


def test_urls_are_stripped_of_every_tracking_parameter():
    """LinkedIn's links carry a one-time sign-in token. None of it may be stored."""
    for card in cards():
        assert card.url.startswith("https://www.linkedin.com/jobs/view/")
        assert "?" not in card.url and "otpToken" not in card.url
        assert card.external_id and card.external_id in card.url


def test_the_url_cleaner_handles_the_raw_form():
    url, job_id = clean_linkedin_url(
        "https://www.linkedin.com/comm/jobs/view/4200000001/?trackingId=a&otpToken=b")
    assert (url, job_id) == ("https://www.linkedin.com/jobs/view/4200000001/", "4200000001")


def test_a_re_poster_is_flagged_rather_than_mistaken_for_the_firm():
    reposted = [c for c in cards() if c.raw["reposted_by"]]
    assert len(reposted) == 2
    assert all(c.raw["reposted_by"] == "Ledgerline Careers" for c in reposted)


def test_a_saved_search_alert_parses_with_the_same_logic():
    """jobalerts-noreply uses the same card layout as the digest."""
    body = ("Your job alert for summer analyst in New York City Metropolitan Area\n\n"
            "Summer Analyst 2027 - Investment Banking\nJ.P. Morgan\nNew York, NY\n"
            "$110K/yr - $120K/yr\nActively recruiting\n"
            "View job: https://www.linkedin.com/comm/jobs/view/4100000001/?trk=x\n")
    postings = parse_alert('"summer analyst": J.P. Morgan - Summer Analyst 2027 and more',
                           body, SENT, sender="jobalerts-noreply@linkedin.com")
    assert len(postings) == 1
    assert postings[0].employer == "J.P. Morgan"
    assert postings[0].location == "New York, NY"
    assert postings[0].raw["pay"] == "$110K/yr - $120K/yr"


def test_nothing_in_the_email_no_postings():
    assert parse_linkedin("", SENT) == []
    assert parse_linkedin("See all jobs https://www.linkedin.com/comm/jobs", SENT) == []


# ------------------------------------------------------ what the gate did

def test_sales_and_trading_is_finance_not_sales():
    """A real card in this shape was rejected as off-function until this was fixed."""
    markets = cards()[0]
    assert score(markets, {"class_standing": "senior"}).rejected_by != "function"


@pytest.mark.parametrize("title", ["Sales & Trading Summer Analyst",
                                   "Global Markets Sales and Trading Analyst"])
def test_sales_and_trading_variants_survive(title):
    result = score(RawPosting(employer="X", title=title, url="u", source="t",
                              location="New York, NY"))
    assert result.rejected_by != "function"


def test_a_real_sales_role_is_still_off_function():
    media = next(c for c in cards() if c.employer == "Marrowfield Media")
    assert score(media).rejected_by == "function"


def test_software_engineering_is_caught_as_well_as_software_engineer():
    engineering = next(c for c in cards() if "VTSI" in c.employer)
    assert score(engineering).rejected_by == "technical"


@pytest.mark.parametrize("location", ["Chantilly", "Boise, Idaho", "United States",
                                      "New York City Metropolitan Area"])
def test_bare_and_full_state_us_locations_pass_the_gate(location):
    result = score(RawPosting(employer="X", title="Investment Analyst", url="u",
                              source="t", location=location))
    assert result.rejected_by != "geography"


def test_a_foreign_city_region_pair_is_still_refused():
    result = score(RawPosting(employer="X", title="Investment Analyst", url="u",
                              source="t", location="Kyiv, Ukraine"))
    assert result.rejected_by == "geography"


# ---------------------------------------------------------------- aliases

REGISTRY = [
    {"name": "JPMorgan", "aliases": ["JPMorgan Chase & Co."], "priority": 1,
     "tracks": ["banking"]},
    {"name": "BlackRock", "priority": 1, "tracks": ["quant"]},
    {"name": "DRW", "priority": 2},
]


@pytest.mark.parametrize("listed,registry_name", [
    ("J.P. Morgan", "JPMorgan"),
    ("JPMorgan Chase & Co.", "JPMorgan"),
    ("BlackRock, Inc.", "BlackRock"),
    ("BlackRock Financial Management", "BlackRock"),
    ("DRW", "DRW"),
])
def test_linkedin_spellings_resolve_to_the_registry(listed, registry_name):
    assert Aliases(REGISTRY).find(listed)["name"] == registry_name


def test_a_short_name_matches_exactly_only():
    """DRW must not swallow a different firm that happens to start with DRW."""
    assert Aliases(REGISTRY).find("DRW Holdings Trust Company") is None


def test_adopting_a_registry_firm_takes_its_priority_and_tracks():
    posting = RawPosting(employer="J.P. Morgan", title="Analyst", url="u", source="linkedin")
    assert Aliases(REGISTRY).adopt(posting)
    assert posting.employer == "JPMorgan"
    assert posting.employer_priority == 1 and posting.employer_tracks == ("banking",)
    assert posting.raw["listed_as"] == "J.P. Morgan"


def test_a_linkedin_copy_dedupes_against_the_firm_s_own_board(conn, monkeypatch):
    """Discovered on JPMorgan's own board first, then seen on LinkedIn: one posting."""
    own_board = RawPosting(employer="JPMorgan", title="Investment Banking Analyst",
                           url="https://jpmc/1", source="oracle",
                           location="New York, NY", description="x" * 400)
    discover._store(conn, own_board, score(own_board))

    body = ("Investment Banking Analyst\nJ.P. Morgan\nNew York, NY\n"
            "View job: https://www.linkedin.com/comm/jobs/view/4100000002/?x=y\n")
    result = discover.ingest_alerts(conn, [discover.Message(
        subject="x", body=body, received=_dt.date.today(), sender=LI)], employers=REGISTRY)
    assert result.already_known == 1 and result.created == []


# ----------------------------------------------------------- the pipeline

def test_ingestion_files_linkedin_postings_and_names_unknown_firms(conn):
    body = ("Summer Analyst 2027\nGoldman Sachs\nNew York, NY\nActively recruiting\n"
            "View job: https://www.linkedin.com/comm/jobs/view/4100000003/?x=y\n\n"
            "---------\n\nSummer Analyst 2027\nJ.P. Morgan\nNew York, NY\n"
            "View job: https://www.linkedin.com/comm/jobs/view/4100000004/?x=y\n")
    result = discover.ingest_alerts(conn, [discover.Message(
        subject="x", body=body, received=_dt.date.today(), sender=LI)], employers=REGISTRY)
    filed = {db.get_posting(conn, slug).company for slug in result.created}
    assert filed == {"Goldman Sachs", "JPMorgan"}
    assert result.new_employers == {"Goldman Sachs": 1}     # JPMorgan is known


def test_stored_linkedin_postings_carry_no_token(conn):
    body = FIXTURE.read_text()
    result = discover.ingest_alerts(conn, [discover.Message(
        subject="x", body=body, received=SENT, sender=LI)], employers=[])
    for slug in result.created:
        stored = db.get_posting(conn, slug)
        assert "otpToken" not in stored.jd_raw and "REDACTED" not in (stored.source_url or "")


def test_old_alerts_are_skipped_when_a_limit_is_set(conn):
    old = discover.Message(subject="x", body=FIXTURE.read_text(), received=SENT, sender=LI)
    result = discover.ingest_alerts(conn, [old], employers=[], max_age_days=21)
    assert result.skipped_old == 1 and result.fetched == 0


def test_a_linkedin_email_that_parses_to_nothing_trips_the_canary(conn):
    changed = discover.Message(subject="Your job alert", received=_dt.date.today(),
                               sender="jobalerts-noreply@linkedin.com",
                               body="A layout LinkedIn has not used before.")
    result = discover.ingest_alerts(conn, [changed], employers=[])
    assert result.unparsed == ["Your job alert"]


def test_title_only_postings_explain_how_to_attach_the_description(conn):
    body = ("Investment Analyst\nAcme Capital\nNew York, NY\n"
            "View job: https://www.linkedin.com/comm/jobs/view/4100000005/?x=y\n")
    result = discover.ingest_alerts(conn, [discover.Message(
        subject="x", body=body, received=_dt.date.today(), sender=LI)], employers=[])
    stored = db.get_posting(conn, result.created[0])
    assert "apply describe" in stored.jd_raw
