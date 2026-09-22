"""A firm's own senior grades, and running the gate again over what is filed.

A bank calls its post-MBA grade "Associate"; a fund often calls its graduate
hire the same thing. So the grade is a registry setting per firm, not a global
pattern. And a rule learned today has to reach what was filed last week, which
is what `rescore` is for.
"""

from __future__ import annotations

from apply import db, digest as digest_mod, discover
from apply.models import Posting, Status
from apply.score import Verdict, score
from apply.sources import ats
from apply.sources.base import RawPosting

BANK = {"name": "Example Bank", "aliases": ["Example Bank & Co."], "ats": "oracle",
        "senior_grades": ["associate"], "priority": 1}
BODY = "Undergraduates graduating in 2027 join a ten-week programme in New York. " * 6


def raw(title, employer="Example Bank", grades=()):
    return RawPosting(employer=employer, title=title, url="u", source="oracle",
                      location="New York, NY, United States", description=BODY,
                      employer_senior_grades=grades)


# ------------------------------------------------------------ the grade


def test_a_firms_senior_grade_rejects_at_that_firm():
    verdict = score(raw("Quantitative Research - Markets - Associate", grades=("associate",)))
    assert verdict.verdict is Verdict.REJECT and verdict.rejected_by == "seniority"
    assert "Example Bank" in verdict.reasons[0]


def test_the_same_title_elsewhere_is_not_senior():
    assert score(raw("Quantitative Research - Markets - Associate")).rejected_by != "seniority"


def test_a_grade_matches_as_a_whole_word():
    verdict = score(raw("Associated Markets Summer Analyst Program", grades=("associate",)))
    assert verdict.rejected_by != "seniority"


def test_the_registry_setting_reaches_board_postings():
    assert ats._common(BANK)["employer_senior_grades"] == ("associate",)


def test_an_alert_posting_adopts_the_firms_grades():
    posting = raw("Summer Associate", employer="Example Bank & Co.")
    assert discover.Aliases([BANK]).adopt(posting)
    assert posting.employer_senior_grades == ("associate",)
    assert score(posting).rejected_by == "seniority"


# --------------------------------------------------------------- rescore


def filed(conn, slug, role, *, verdict="maybe", value=60, discovered=True,
          company="Example Bank", status=None):
    jd = (f"[discovered 2026-09-21 via oracle]\n{company} — {role}\n"
          f"Location: New York, NY\nSource: https://x/{slug}\n{BODY}")
    posting = db.create_posting(conn, Posting(
        slug=slug, company=company, role=role, track="banking", jd_raw=jd,
        location="New York, NY, United States", source="oracle", priority=1,
        score=value, score_verdict=verdict, score_reasons="as filed",
        discovered_at="2026-09-21 20:00:00" if discovered else None))
    app = db.get_application(conn, posting.id)
    if status is Status.GENERATED:
        db.transition(conn, app.id, Status.GENERATED, via="gen")
    return app


def test_rescore_screens_out_what_the_gate_now_rejects(conn):
    app = filed(conn, "bank-assoc", "Rates Trading - Associate")

    [change] = discover.rescore(conn, employers=[BANK])

    assert change.before == (60, "maybe")
    assert change.after.verdict is Verdict.REJECT
    row = db.row_for(conn, "bank-assoc")
    assert row is not None, "kept, not deleted"
    assert row.posting.score_verdict == "reject" and row.posting.score == 0
    assert digest_mod.screened_out(row)
    assert not digest_mod.in_pipeline(row)
    assert digest_mod.headline(conn)["open"] == 0
    assert any("rescored maybe 60 -> reject" in (e.detail or "")
               for e in db.events(conn, app.id))


def test_rescore_leaves_the_track_and_the_text_alone(conn):
    filed(conn, "bank-assoc", "Rates Trading - Associate")
    before = db.get_posting(conn, "bank-assoc")
    discover.rescore(conn, employers=[BANK])
    after = db.get_posting(conn, "bank-assoc")
    assert (after.track, after.jd_raw) == (before.track, before.jd_raw)


def test_rescore_never_touches_a_posting_added_by_hand(conn):
    filed(conn, "mine", "Rates Trading - Associate", discovered=False)
    assert discover.rescore(conn, employers=[BANK]) == []
    row = db.row_for(conn, "mine")
    assert row.posting.score_verdict == "maybe"
    assert not digest_mod.screened_out(row)


def test_rescore_never_touches_a_posting_with_a_letter(conn):
    filed(conn, "written", "Rates Trading - Associate", status=Status.GENERATED)
    assert discover.rescore(conn, employers=[BANK]) == []
    assert db.get_posting(conn, "written").score_verdict == "maybe"


def test_a_dry_run_writes_nothing(conn):
    app = filed(conn, "bank-assoc", "Rates Trading - Associate")
    assert len(discover.rescore(conn, employers=[BANK], dry_run=True)) == 1
    assert db.get_posting(conn, "bank-assoc").score_verdict == "maybe"
    assert not any("rescored" in (e.detail or "") for e in db.events(conn, app.id))


def test_rescore_is_idempotent(conn):
    filed(conn, "bank-assoc", "Rates Trading - Associate")
    discover.rescore(conn, employers=[BANK])
    assert discover.rescore(conn, employers=[BANK]) == []


def test_a_posting_still_worth_reading_stays_in_the_pipeline(conn):
    filed(conn, "bank-sa", "2027 Markets Summer Analyst Program", value=10)
    [change] = discover.rescore(conn, employers=[BANK])
    assert change.after.verdict is not Verdict.REJECT
    assert digest_mod.in_pipeline(db.row_for(conn, "bank-sa"))


def test_the_gate_reads_the_body_without_the_header_or_placeholder():
    jd = ("[discovered 2026-09-21 via email]\nAcme — Intern\nLocation: NY\n"
          f"Source: https://x/intern-2027\n{discover._NO_DESCRIPTION}")
    assert discover._scoring_body(jd) == ""
    assert discover._scoring_body(f"[discovered x]\na\nb\nc\n{BODY}") == BODY.strip()
    assert discover._scoring_body("pasted by hand") == "pasted by hand"
