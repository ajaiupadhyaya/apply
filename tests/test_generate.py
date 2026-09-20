"""Escaping, composition, and the lint gate."""

from __future__ import annotations

import pytest

from apply.generate import (
    PROHIBITED, compose, jd_anchors, latex_escape, letter_from_body, lint,
    select_resume,
)
from apply.models import Track
from conftest import posting_from


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
