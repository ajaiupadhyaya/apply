"""`apply describe`: attaching the full posting to a title-only one."""

from __future__ import annotations

import datetime as _dt

from typer.testing import CliRunner

from apply import db, discover
from apply.cli import app
from apply.score import score
from apply.sources.base import RawPosting

FULL = (
    "Summer Analyst Program, Investment Banking — New York. Open to undergraduates "
    "graduating in 2027. Analysts support deal execution across M&A, build "
    "comparable company analyses and LBO models, and prepare pitch materials for "
    "the coverage group. Application deadline: October 30, 2026. "
) * 2


def _title_only(conn, title="Summer Analyst 2027") -> str:
    posting = RawPosting(employer="Acme Capital", title=title, url="https://li/1",
                         source="linkedin", location="New York, NY")
    return discover._store(conn, posting, score(posting, {"class_standing": "senior"}))


def test_describe_attaches_the_text_and_rescores(conn, tmp_path):
    slug = _title_only(conn)
    before = db.get_posting(conn, slug)
    assert discover._NO_DESCRIPTION in before.jd_raw

    source = tmp_path / "jd.txt"
    source.write_text(FULL)
    result = CliRunner().invoke(app, ["describe", slug, "--file", str(source)])
    assert result.exit_code == 0, result.output

    after = db.get_posting(conn, slug)
    assert discover._NO_DESCRIPTION not in after.jd_raw
    assert "LBO models" in after.jd_raw
    assert after.jd_raw.startswith(before.jd_raw.split(discover._NO_DESCRIPTION)[0])  # header kept
    assert after.deadline == _dt.date(2026, 10, 30)
    assert after.track == "banking"
    assert after.score is not None


def test_describe_refuses_something_too_short(conn, tmp_path):
    slug = _title_only(conn)
    source = tmp_path / "jd.txt"
    source.write_text("Great job, apply now.")
    result = CliRunner().invoke(app, ["describe", slug, "--file", str(source)])
    assert result.exit_code != 0
    assert discover._NO_DESCRIPTION in db.get_posting(conn, slug).jd_raw


def test_the_full_text_can_disqualify_what_the_title_did_not(conn, tmp_path):
    """The body is where the disqualifiers live."""
    slug = _title_only(conn, title="Investment Analyst")
    source = tmp_path / "jd.txt"
    source.write_text("Investment Analyst in New York. We require 5+ years of relevant "
                      "experience in credit research and portfolio management. " * 4)
    CliRunner().invoke(app, ["describe", slug, "--file", str(source)])
    assert db.get_posting(conn, slug).score_verdict == "reject"
