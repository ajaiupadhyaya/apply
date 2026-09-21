"""Escaping, composition, and the lint gate."""

from __future__ import annotations

import pytest

from apply.generate import (
    PROHIBITED, jd_anchors, latex_escape, lint, package_from_files, select_resume,
)
from apply.models import Track
from conftest import FakeClaude, posting_from

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


# ----------------------------------------------------------------- routing

def test_quant_postings_route_to_the_quant_resume_and_ohcamel(profile, blackrock_jd):
    from apply.context import proof_asset

    posting = posting_from(blackrock_jd)
    assert posting.track == Track.QUANT.value
    assert "OhCamel" in proof_asset(profile, posting.track)
    assert select_resume(posting.track) == "resume_quant"


def test_allocator_postings_lead_with_the_consulting_role(profile, vcimco_jd):
    from apply.context import proof_asset

    posting = posting_from(vcimco_jd)
    assert posting.track == Track.ALLOCATOR.value
    asset = proof_asset(profile, posting.track)
    assert "consulting" in asset and "OhCamel" not in asset


def test_every_track_has_a_default_proof_asset(profile):
    from apply.context import proof_asset

    for track in Track:
        assert proof_asset(profile, track.value), track


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


def test_a_clean_grounded_draft_passes(profile, vcimco_jd, fake_claude):
    from apply import writer

    posting = posting_from(vcimco_jd)
    assert lint(writer.full_text(fake_claude.package()), profile, posting).ok


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
    """Acme Capital, 3M, 7-Eleven. The firm's own name is sourced by definition."""
    posting = posting_from(vcimco_jd, company="Acme Capital", role="Quantitative Researcher")
    assert lint("I am applying to Acme Capital.", profile, posting).ok

    numeric = posting_from(vcimco_jd, company="3M", role="Analyst")
    assert lint("I am applying to 3M.", profile, numeric).ok


def test_a_number_from_the_profile_is_allowed(profile, vcimco_jd):
    posting = posting_from(vcimco_jd)
    assert lint("I graduate in May 2027.", profile, posting).ok


def test_an_ask_placeholder_fails(profile, vcimco_jd):
    posting = posting_from(vcimco_jd)
    assert not lint("I started in ASK.", profile, posting).ok


@pytest.mark.parametrize("sentence", [
    "I will require sponsorship to begin work.",
    "I would need visa sponsorship.",
])
def test_a_sponsorship_claim_contradicting_the_profile_fails(profile, vcimco_jd, sentence):
    """The one field where a wrong answer is disqualifying gets its own check."""
    assert not lint(sentence, profile, posting_from(vcimco_jd)).ok


@pytest.mark.parametrize("sentence", [
    "I will not require sponsorship, now or in the future.",
    "I won't need sponsorship.",
    "I am authorized to work without sponsorship.",
    "I do not require employment sponsorship.",
])
def test_a_correct_sponsorship_statement_passes(profile, vcimco_jd, sentence):
    assert lint(sentence, profile, posting_from(vcimco_jd)).ok


def test_a_number_from_a_context_document_is_sourced(profile, vcimco_jd, workspace):
    """A figure the owner put in data/context/ is theirs to cite."""
    directory = workspace / "data" / "context"
    directory.mkdir(exist_ok=True)
    (directory / "ohcamel.md").write_text("The engine has 210 tests.")
    assert lint("OhCamel has 210 tests.", profile, posting_from(vcimco_jd)).ok
    assert not lint("OhCamel has 950 tests.", profile, posting_from(vcimco_jd)).ok


# -------------------------------------------------------------- variants

def test_resume_variant_selection():
    assert select_resume(Track.QUANT) == "resume_quant"
    for track in (Track.BANKING, Track.ALLOCATOR, Track.CORPORATE):
        assert select_resume(track) == "resume_traditional"


def test_a_hand_edited_body_reads_back_with_its_closing(tmp_path):
    (tmp_path / "body.md").write_text(
        "<!-- instructions -->\n\nFirst para.\n\nSecond para.\n\nThe closing.")
    package = package_from_files(tmp_path)
    assert package.paragraphs() == ["First para.", "Second para."]
    assert package.closing == "The closing."


def test_extra_hand_edited_paragraphs_are_kept_not_dropped(tmp_path):
    (tmp_path / "body.md").write_text("\n\n".join(f"P{i}." for i in range(1, 7)) + "\n\nEnd.")
    package = package_from_files(tmp_path)
    assert "P6." in " ".join(package.paragraphs())


def test_answers_read_back_from_answers_md(tmp_path):
    (tmp_path / "body.md").write_text("Para.\n\nClose.")
    (tmp_path / "answers.md").write_text(
        "## Why this role (short)\n\nShort one.\n\n## Why this role (long)\n\nLong one.")
    package = package_from_files(tmp_path)
    assert (package.why_role_short, package.why_role_long) == ("Short one.", "Long one.")


# ----------------------------------------------------- filenames and sweep

def test_two_roles_at_one_firm_get_different_filenames(profile, vcimco_jd):
    """Three letters all called one shared filename is how the
    wrong one gets uploaded."""
    from apply.generate import _document_tag

    a = posting_from(vcimco_jd, company="Acme Capital", role="Quantitative Researcher Intern")
    b = posting_from(vcimco_jd, company="Acme Capital", role="Fund Flow Quantitative Researcher")
    assert _document_tag(a) != _document_tag(b)
    assert _document_tag(a).startswith("Acme_Capital")


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

    posting = posting_from(vcimco_jd, company="Acme Capital", role="Quantitative Researcher")
    first = gen_mod.build(profile, posting, caller=FakeClaude())
    assert first.letter_pdf.exists()

    posting.role = "Fund Flow Quantitative Researcher"
    second = gen_mod.build(profile, posting, caller=FakeClaude())
    assert second.letter_pdf.exists()
    assert second.letter_pdf != first.letter_pdf
    assert not first.letter_pdf.exists(), "the superseded letter was left behind"
    assert len(list(second.directory.glob("*_Cover_Letter_*.pdf"))) == 1
