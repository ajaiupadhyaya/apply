"""Escaping, composition, and the lint gate."""

from __future__ import annotations

import pytest

from apply.generate import (
    PROHIBITED, compose, jd_anchors, latex_escape, letter_from_body, lint,
    select_resume,
)
from apply.models import Track
from conftest import posting_from

import shutil

needs_latex_gen = pytest.mark.skipif(
    shutil.which("pdflatex") is None, reason="pdflatex is not installed")


# ------------------------------------------------------------- escaping

@pytest.mark.parametrize("raw,expected", [
    ("Smith & Co.", r"Smith \& Co."),
    ("100% remote", r"100\% remote"),
    ("$110,000", r"\$110,000"),
    ("C#", r"C\#"),
    ("snake_case", r"snake\_case"),
    ("{braces}", r"\{braces\}"),
    ("a~b", r"a\textasciitilde{}b"),
    ("x^2", r"x\textasciicircum{}2"),
    ("back\\slash", r"back\textbackslash{}slash"),
])
def test_latex_escape(raw, expected):
    assert latex_escape(raw) == expected


def test_escape_handles_pasted_typography():
    assert latex_escape("“quoted” — dash") == "``quoted'' --- dash"


def test_escape_of_none_is_empty():
    assert latex_escape(None) == ""


# ---------------------------------------------------------- composition

def test_quant_proof_paragraph_is_ohcamel(profile, blackrock_jd):
    posting = posting_from(blackrock_jd)
    assert posting.track == Track.QUANT.value
    assert "OhCamel" in compose(profile, posting).paragraphs[1]


def test_allocator_proof_paragraph_is_the_consulting_role(profile, vcimco_jd):
    posting = posting_from(vcimco_jd)
    assert posting.track == Track.ALLOCATOR.value
    proof = compose(profile, posting).paragraphs[1]
    assert "Bloomberg Terminal" in proof
    assert "OhCamel" not in proof


def test_every_track_composes_four_paragraphs(profile, vcimco_jd):
    for track in Track:
        posting = posting_from(vcimco_jd, track=track.value)
        assert len(compose(profile, posting).paragraphs) == 4


def test_the_closing_states_the_sponsorship_answer(profile, vcimco_jd):
    closing = compose(profile, posting_from(vcimco_jd)).closing
    assert "will not require sponsorship" in closing


def test_a_role_that_names_itself_does_not_get_the_word_role(profile, vcimco_jd):
    program = posting_from(vcimco_jd, role="2027 Analyst Program")
    assert "2027 Analyst Program at" in compose(profile, program).paragraphs[0]
    plain = posting_from(vcimco_jd, role="Investment Intern")
    assert "Investment Intern role at" in compose(profile, plain).paragraphs[0]


# --------------------------------------------------------------- anchors

def test_anchors_find_named_systems(blackrock_jd):
    phrases = [a.phrase for a in jd_anchors(blackrock_jd, "BlackRock",
                                            "Analyst Program", "New York, NY")]
    assert "Aladdin Engineering" in phrases


def test_anchors_exclude_the_employer_the_place_and_the_job(vcimco_jd):
    anchors = jd_anchors(vcimco_jd, "VCIMCO", "Investment Intern", "Richmond, Virginia")
    lowered = [a.phrase.lower() for a in anchors]
    assert not any("vcimco" in p for p in lowered)
    assert not any("intern" in p for p in lowered)
    assert not any("richmond" in p for p in lowered)


def test_a_department_name_gets_its_article_back(vcimco_jd):
    anchors = jd_anchors(vcimco_jd, "VCIMCO", "Investment Intern", "Richmond, Virginia")
    by_phrase = {a.phrase: a for a in anchors}
    assert by_phrase["Investment Committee"].with_article == "the Investment Committee"


def test_a_proper_name_stands_alone(blackrock_jd):
    anchors = {a.phrase: a for a in jd_anchors(blackrock_jd, "BlackRock", "Analyst", "NY")}
    assert anchors["Aladdin Engineering"].with_article == "Aladdin Engineering"


# ------------------------------------------------------------------ lint

@pytest.mark.parametrize("phrase", PROHIBITED)
def test_every_prohibited_phrase_is_caught(profile, vcimco_jd, phrase):
    posting = posting_from(vcimco_jd)
    result = lint(f"I am {phrase} about this role.", profile, posting)
    assert not result.ok
    assert any(phrase in e for e in result.errors)


def test_a_clean_composed_letter_passes(profile, vcimco_jd):
    posting = posting_from(vcimco_jd)
    assert lint(compose(profile, posting).full_text, profile, posting).ok


def test_unsourced_superlatives_fail(profile, vcimco_jd):
    posting = posting_from(vcimco_jd)
    result = lint("VCIMCO is a world-class investment office.", profile, posting)
    assert not result.ok
    assert any("world-class" in e for e in result.errors)


def test_a_superlative_the_posting_used_is_allowed(profile, vcimco_jd):
    posting = posting_from(vcimco_jd, jd_raw=vcimco_jd + "\nWe are a leading office.")
    assert lint("It is a leading office.", profile, posting).ok


def test_an_invented_number_fails(profile, vcimco_jd):
    posting = posting_from(vcimco_jd)
    result = lint("I have managed $4,200,000 in assets.", profile, posting)
    assert not result.ok
    assert any("unsourced figure" in e for e in result.errors)


def test_a_number_from_the_posting_is_allowed(profile, vcimco_jd):
    posting = posting_from(vcimco_jd)
    assert lint("The posting mentions $20/hr.", profile, posting).ok


def test_a_company_name_containing_a_digit_is_not_a_hallucination(profile, vcimco_jd):
    """Point72, 3M, 7-Eleven. The firm's own name is sourced by definition."""
    posting = posting_from(vcimco_jd, company="Point72", role="Quantitative Researcher")
    assert lint("I am applying to Point72.", profile, posting).ok

    numeric = posting_from(vcimco_jd, company="3M", role="Analyst")
    assert lint("I am applying to 3M.", profile, numeric).ok


def test_a_number_from_the_profile_is_allowed(profile, vcimco_jd):
    posting = posting_from(vcimco_jd)
    assert lint("I graduate in May 2027.", profile, posting).ok


def test_an_ask_placeholder_fails(profile, vcimco_jd):
    posting = posting_from(vcimco_jd)
    assert not lint("I started in ASK.", profile, posting).ok


def test_a_missing_anchor_warns_but_does_not_block(profile, vcimco_jd):
    posting = posting_from(vcimco_jd)
    result = lint("NAME THE SPECIFIC PLATFORM here.", profile, posting)
    assert result.ok
    assert result.warnings


# -------------------------------------------------------------- variants

def test_resume_variant_selection():
    assert select_resume(Track.QUANT) == "resume_quant"
    for track in (Track.BANKING, Track.ALLOCATOR, Track.CORPORATE):
        assert select_resume(track) == "resume_traditional"


def test_body_md_overrides_the_composed_paragraphs(profile, vcimco_jd):
    posting = posting_from(vcimco_jd)
    letter = letter_from_body(profile, posting, "First para.\n\nSecond para.")
    assert letter.paragraphs[0] == "First para."


# ----------------------------------------------------- filenames and sweep

def test_two_roles_at_one_firm_get_different_filenames(profile, vcimco_jd):
    """Three letters all called AJ_Upadhyaya_Cover_Letter_Point72.pdf is how the
    wrong one gets uploaded."""
    from apply.generate import _document_tag

    a = posting_from(vcimco_jd, company="Point72", role="Quantitative Researcher Intern")
    b = posting_from(vcimco_jd, company="Point72", role="Fund Flow Quantitative Researcher")
    assert _document_tag(a) != _document_tag(b)
    assert _document_tag(a).startswith("Point72")


def test_the_tag_drops_filler_but_keeps_the_distinguishing_words(profile, vcimco_jd):
    from apply.generate import _document_tag

    tag = _document_tag(posting_from(
        vcimco_jd, company="BlackRock", role="2027 Full-Time Analyst Program (AMRS)"))
    assert "2027" not in tag and "Program" not in tag
    assert "Analyst" in tag and "AMRS" in tag


def test_a_role_of_only_filler_still_yields_a_name(profile, vcimco_jd):
    from apply.generate import _document_tag

    assert _document_tag(posting_from(vcimco_jd, company="Acme", role="Internship")) == "Acme"


@needs_latex_gen
def test_regenerating_under_a_new_name_removes_the_old_pdf(profile, vcimco_jd):
    from apply import generate as gen_mod

    posting = posting_from(vcimco_jd, company="Point72", role="Quantitative Researcher")
    first = gen_mod.build(profile, posting)
    assert first.letter_pdf.exists()

    posting.role = "Fund Flow Quantitative Researcher"
    second = gen_mod.build(profile, posting)
    assert second.letter_pdf.exists()
    assert second.letter_pdf != first.letter_pdf
    assert not first.letter_pdf.exists(), "the superseded letter was left behind"
    assert len(list(second.directory.glob("*_Cover_Letter_*.pdf"))) == 1
