"""The resume as an ATS reads it, the source-host check, the funnel and the gaps."""

from __future__ import annotations

import shutil

import pytest

from apply import ats, db, stats
from apply.models import Posting, Status
from apply.resolve import host_check

needs_latex = pytest.mark.skipif(
    shutil.which("pdflatex") is None, reason="pdflatex is not installed")


# ------------------------------------------------------------- text layer


def test_an_en_dashed_date_range_is_a_problem():
    problems = ats.parse_problems("Analyst\nAug 2025 – Present\n", email=None, phone=None)
    assert any("non-ASCII dash" in p for p in problems)


def test_an_ascii_date_range_is_clean():
    assert ats.parse_problems("Analyst\nAug 2025 - Present\n", email=None, phone=None) == []


def test_a_dash_on_the_next_line_does_not_join_a_year():
    text = "Graduated 2025\n– led the desk\n"
    assert ats.non_ascii_date_ranges(text) == []


def test_unreadable_glyphs_are_reported():
    problems = ats.parse_problems("Name (cid:12) more", email=None, phone=None)
    assert any("unreadable glyph" in p for p in problems)


def test_contact_details_must_be_literal_text():
    text = "Jane Doe  jane@example.com  (804) 555-0100"
    assert ats.parse_problems(text, email="jane@example.com", phone="804-555-0100") == []
    problems = ats.parse_problems("Jane Doe  Envelope", email="jane@example.com",
                                  phone="804-555-0100")
    assert len(problems) == 2


def test_a_blank_text_layer_is_one_problem():
    assert len(ats.parse_problems("  \n ", email="a@b.c", phone=None)) == 1


# --------------------------------------------------------------- keywords


@pytest.mark.parametrize("text, present, absent", [
    ("Python, R, and SQL required", {"Python", "R", "SQL"}, set()),
    ("our R&D group", set(), {"R"}),
    ("C++ or C# a plus", {"C++", "C#"}, set()),
    ("JavaScript experience", {"JavaScript"}, {"Java"}),
    ("excellent communication", set(), {"Excel"}),
    ("derivatives of the loss", set(), {"derivatives"}),
    ("trade equity derivatives", {"derivatives"}, set()),
    ("CFA charter", {"CFA"}, set()),
])
def test_vocabulary_boundaries(text, present, absent):
    found = set(ats.terms_in(text))
    assert present <= found
    assert not (absent & found)


def test_coverage_sorts_every_named_term_into_one_pile():
    jd = "Requires Python, SQL, VBA and Tableau."
    resume = "Skills: Python, SQL"
    sources = "skills: Python, SQL. Wrote VBA macros for the fund."
    cov = ats.coverage(jd, resume, sources)
    assert cov.covered == ["Python", "SQL"]
    assert cov.unused == ["VBA"]
    assert cov.gaps == ["Tableau"]
    assert "2/4" in cov.summary()


def test_a_posting_that_names_nothing_has_no_summary():
    assert ats.coverage("Be curious.", "", "").summary() is None


# ------------------------------------------------------------ source host


@pytest.mark.parametrize("url, company, kind", [
    ("https://boards.greenhouse.io/janestreet/jobs/1", "Jane Street", "ats"),
    ("https://blackrock.wd1.myworkdayjobs.com/x", "BlackRock", "ats"),
    ("https://careers.janestreet.com/jobs", "Jane Street", "employer"),
    ("https://evil-greenhouse.io/jobs", None, "unverified"),
    ("https://boards.greenhouse.io.evil.com/jobs", None, "unverified"),
    ("https://greenhouse.io@evil.com/", None, "unverified"),
    ("https://citadel-careers.xyz/apply", "Citadel", "unverified"),
])
def test_host_check(url, company, kind):
    assert host_check(url, company)[0] == kind


def test_no_url_no_verdict():
    assert host_check(None, "Acme") is None


# ----------------------------------------------------------------- resume


def test_resume_date_ranges_are_ascii(profile):
    from apply.generate import _resume_context

    context, _ = _resume_context(profile)
    for job in context["experience"]:
        assert "–" not in (job["dates"] or "")


@needs_latex
def test_the_built_resume_reads_clean(profile, tmp_path):
    from apply.generate import compile_pdf, render_resume

    tex = tmp_path / "resume_quant.tex"
    tex.write_text(render_resume(profile, "resume_quant")[0], encoding="utf-8")
    pdf = compile_pdf(tex, max_pages=None)
    text = ats.extract(pdf)
    assert ats.non_ascii_date_ranges(text) == []
    assert not ats.parse_problems(text, email=profile.email or None, phone=None)


# ----------------------------------------------------------------- funnel


def _app(conn, slug, source, path):
    posting = db.create_posting(conn, Posting(
        slug=slug, company=slug.title(), role="Analyst", track="corporate",
        jd_raw="Python and Tableau required.", source=source))
    app = db.get_application(conn, posting.id)
    db.transition(conn, app.id, Status.GENERATED, via="gen")
    db.transition(conn, app.id, Status.READY, via="review")
    db.transition(conn, app.id, Status.SUBMITTED, via="submit")
    for status in path:
        db.transition(conn, app.id, status, via="mark")
    return app


def test_the_funnel_counts_stages_reached_not_current_status(conn):
    _app(conn, "acme", "linkedin", [Status.INTERVIEWING, Status.REJECTED])
    _app(conn, "bolt", "linkedin", [])
    _app(conn, "crux", None, [Status.ACKNOWLEDGED, Status.OFFER])
    rows = {f.channel: f for f in stats.funnel(conn)}
    assert (rows["linkedin"].submitted, rows["linkedin"].responded,
            rows["linkedin"].interviewed) == (2, 1, 1)
    assert rows["manual"].offers == 1
    assert rows["all"].submitted == 3 and rows["all"].interviewed == 2
    assert rows["all"].median_days == 0


def test_an_empty_pipeline_has_no_funnel(conn):
    assert stats.funnel(conn) == []


def test_gaps_tally_across_live_postings_only(conn):
    _app(conn, "acme", None, [])
    _app(conn, "bolt", None, [])
    _app(conn, "dead", None, [Status.REJECTED])
    found = stats.gaps(conn, "I write Python.")
    assert [(g.term, len(g.postings)) for g in found] == [("Tableau", 2)]
