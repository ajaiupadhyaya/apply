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

def test_quant_postings_route_to_the_quant_resume_and_project(profile, quillon_jd):
    from apply.context import proof_asset

    posting = posting_from(quillon_jd)
    assert posting.track == Track.QUANT.value
    assert "Vanilla" in proof_asset(profile, posting.track)
    assert select_resume(posting.track) == "resume_quant"


def test_allocator_postings_lead_with_the_allocator_work(profile, ashcombe_jd):
    from apply.context import proof_asset

    posting = posting_from(ashcombe_jd)
    assert posting.track == Track.ALLOCATOR.value
    asset = proof_asset(profile, posting.track)
    assert "Rents and Transit" in asset and "Vanilla" not in asset


def test_every_track_has_a_default_proof_asset(profile):
    from apply.context import proof_asset

    for track in Track:
        assert proof_asset(profile, track.value), track


# --------------------------------------------------------------- anchors

def test_anchors_find_named_systems(quillon_jd):
    phrases = [a.phrase for a in jd_anchors(quillon_jd, "Quillon Asset Management",
                                            "Analyst Program", "New York, NY")]
    assert "Sextant Engineering" in phrases


def test_anchors_exclude_the_employer_the_place_and_the_job(ashcombe_jd):
    anchors = jd_anchors(ashcombe_jd, "Ashcombe Trust", "Investment Intern",
                         "Hudson, New York")
    lowered = [a.phrase.lower() for a in anchors]
    assert not any("ashcombe" in p for p in lowered)
    assert not any("intern" in p for p in lowered)
    assert not any("hudson" in p for p in lowered)


def test_a_department_name_gets_its_article_back(ashcombe_jd):
    anchors = jd_anchors(ashcombe_jd, "Ashcombe Trust", "Investment Intern",
                         "Hudson, New York")
    by_phrase = {a.phrase: a for a in anchors}
    assert by_phrase["Investment Committee"].with_article == "the Investment Committee"


def test_a_proper_name_stands_alone(quillon_jd):
    anchors = {a.phrase: a
               for a in jd_anchors(quillon_jd, "Quillon Asset Management", "Analyst", "NY")}
    assert anchors["Sextant Engineering"].with_article == "Sextant Engineering"


# ------------------------------------------------------------------ lint

@pytest.mark.parametrize("phrase", PROHIBITED)
def test_every_prohibited_phrase_is_caught(profile, ashcombe_jd, phrase):
    posting = posting_from(ashcombe_jd)
    result = lint(f"I am {phrase} about this role.", profile, posting)
    assert not result.ok
    assert any(phrase in e for e in result.errors)


def test_a_literal_json_escape_is_caught(profile, ashcombe_jd):
    """Found in a live draft: "\\u2014" printed where an em dash was meant."""
    result = lint("The engine is incremental \\u2014 only what changed recomputes.",
                  profile, posting_from(ashcombe_jd))
    assert not result.ok
    assert any("\\u2014" in e for e in result.errors)


def test_the_character_itself_is_fine(profile, ashcombe_jd):
    result = lint("The engine is incremental — only what changed recomputes.",
                  profile, posting_from(ashcombe_jd))
    assert not any("escape" in e for e in result.errors)


def test_a_clean_grounded_draft_passes(profile, ashcombe_jd, fake_claude):
    from apply import writer

    posting = posting_from(ashcombe_jd)
    assert lint(writer.full_text(fake_claude.package()), profile, posting).ok


def test_unsourced_superlatives_fail(profile, ashcombe_jd):
    posting = posting_from(ashcombe_jd)
    result = lint("Ashcombe Trust is a world-class investment office.", profile, posting)
    assert not result.ok
    assert any("world-class" in e for e in result.errors)


def test_a_superlative_the_posting_used_is_allowed(profile, ashcombe_jd):
    """The posting calls itself "a leading limited partner", so the letter may
    say "leading" back. Read off the seed posting itself, not a doctored copy:
    if that word ever leaves the fixture, this test is supposed to notice."""
    assert "leading" in ashcombe_jd
    assert lint("It is a leading office.", profile, posting_from(ashcombe_jd)).ok


def test_an_invented_number_fails(profile, ashcombe_jd):
    posting = posting_from(ashcombe_jd)
    result = lint("I have managed $4,200,000 in assets.", profile, posting)
    assert not result.ok
    assert any("unsourced figure" in e for e in result.errors)


def test_a_number_from_the_posting_is_allowed(profile, ashcombe_jd):
    posting = posting_from(ashcombe_jd)
    assert lint("The posting mentions $20/hr.", profile, posting).ok


def test_a_company_name_containing_a_digit_is_not_a_hallucination(profile, ashcombe_jd):
    """Acme Capital, 3M, 7-Eleven. The firm's own name is sourced by definition."""
    posting = posting_from(ashcombe_jd, company="Acme Capital", role="Quantitative Researcher")
    assert lint("I am applying to Acme Capital.", profile, posting).ok

    numeric = posting_from(ashcombe_jd, company="3M", role="Analyst")
    assert lint("I am applying to 3M.", profile, numeric).ok


def test_a_number_from_the_profile_is_allowed(profile, ashcombe_jd):
    posting = posting_from(ashcombe_jd)
    assert lint("I graduate in June 2027.", profile, posting).ok


def test_an_ask_placeholder_fails(profile, ashcombe_jd):
    posting = posting_from(ashcombe_jd)
    assert not lint("I started in ASK.", profile, posting).ok


@pytest.mark.parametrize("sentence", [
    "I will require sponsorship to begin work.",
    "I would need visa sponsorship.",
])
def test_a_sponsorship_claim_contradicting_the_profile_fails(profile, ashcombe_jd, sentence):
    """The one field where a wrong answer is disqualifying gets its own check."""
    assert not lint(sentence, profile, posting_from(ashcombe_jd)).ok


@pytest.mark.parametrize("sentence", [
    "I will not require sponsorship, now or in the future.",
    "I won't need sponsorship.",
    "I am authorized to work without sponsorship.",
    "I do not require employment sponsorship.",
])
def test_a_correct_sponsorship_statement_passes(profile, ashcombe_jd, sentence):
    assert lint(sentence, profile, posting_from(ashcombe_jd)).ok


def test_a_number_from_a_context_document_is_sourced(profile, ashcombe_jd, workspace):
    """A figure the owner put in data/context/ is theirs to cite."""
    directory = workspace / "data" / "context"
    directory.mkdir(exist_ok=True)
    (directory / "vanilla.md").write_text("The library has 210 tests.")
    assert lint("Vanilla has 210 tests.", profile, posting_from(ashcombe_jd)).ok
    assert not lint("Vanilla has 950 tests.", profile, posting_from(ashcombe_jd)).ok


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

def test_two_roles_at_one_firm_get_different_filenames(profile, ashcombe_jd):
    """Three letters all called one shared filename is how the
    wrong one gets uploaded."""
    from apply.generate import _document_tag

    a = posting_from(ashcombe_jd, company="Acme Capital", role="Quantitative Researcher Intern")
    b = posting_from(ashcombe_jd, company="Acme Capital", role="Fund Flow Quantitative Researcher")
    assert _document_tag(a) != _document_tag(b)
    assert _document_tag(a).startswith("Acme_Capital")


def test_the_tag_drops_filler_but_keeps_the_distinguishing_words(profile, ashcombe_jd):
    from apply.generate import _document_tag

    tag = _document_tag(posting_from(
        ashcombe_jd, company="Quillon Asset Management",
        role="2027 Full-Time Analyst Program (Americas)"))
    assert "2027" not in tag and "Program" not in tag
    assert "Analyst" in tag and "Americas" in tag


def test_a_role_of_only_filler_still_yields_a_name(profile, ashcombe_jd):
    from apply.generate import _document_tag

    assert _document_tag(posting_from(ashcombe_jd, company="Acme", role="Internship")) == "Acme"


@needs_latex_gen
def test_regenerating_under_a_new_name_removes_the_old_pdf(profile, ashcombe_jd):
    from apply import generate as gen_mod

    posting = posting_from(ashcombe_jd, company="Acme Capital", role="Quantitative Researcher")
    first = gen_mod.build(profile, posting, caller=FakeClaude())
    assert first.letter_pdf.exists()

    posting.role = "Fund Flow Quantitative Researcher"
    second = gen_mod.build(profile, posting, caller=FakeClaude())
    assert second.letter_pdf.exists()
    assert second.letter_pdf != first.letter_pdf
    assert not first.letter_pdf.exists(), "the superseded letter was left behind"
    assert len(list(second.directory.glob("*_Cover_Letter_*.pdf"))) == 1


# ------------------------------- what the wizard did not ask about
#
# The lint reads the letter, which is prose a model wrote and can be made to
# rewrite. The resume is rendered straight out of the profile, so no amount of
# reading the draft catches an unfilled field in it: `apply setup` never asks
# about your last job, and the PDF printed what it found — "ASK, ASK  Present"
# under EXPERIENCE, above an empty PROJECTS heading.


def _wizard_profile(workspace, **overrides):
    """A profile exactly as the interactive wizard leaves it."""
    from apply import setup
    from apply.profile import Profile

    answers = setup.Answers(**{
        "name": "Rae Mercer", "email": "rae@example.com",
        "school": "Example University", "degree": "BS Finance",
        "grad_expected": "2027-05", "city": "New York, NY", **overrides})
    setup.write_profile(setup.profile_from(answers),
                        workspace / "data" / "profile.yaml", force=True)
    return Profile.load()


def test_an_unfilled_profile_value_never_reaches_a_document(workspace, ashcombe_jd):
    from apply import generate as gen_mod

    profile = _wizard_profile(workspace)
    assert "experience[0].org" in profile.document_gaps()

    caller = FakeClaude()
    with pytest.raises(ValueError) as refused:
        gen_mod.build(profile, posting_from(ashcombe_jd), caller=caller)

    # It names the field, so the reader knows which one to go and write…
    assert "experience[0].org" in str(refused.value)
    assert "apply doctor" in str(refused.value)
    # …and it refuses before the model is called, so a profile full of holes
    # does not cost anything to find out about.
    assert caller.calls == []


def test_a_value_no_document_prints_is_not_a_reason_to_refuse(workspace):
    """A gap with somewhere else to go is not a gap in a deliverable.

    `education[0].start` is never rendered, and an ASK start date on a job is
    dropped from the line by `_month_year` rather than printed — so neither is
    a reason to refuse to build. Refusing on every ASK would make the wizard's
    own output unusable, which is the opposite of the point.
    """
    profile = _wizard_profile(workspace)
    gaps = profile.document_gaps()

    for unresolved_but_harmless in ("education[0].start", "availability.full_time"):
        assert unresolved_but_harmless in profile.unresolved()
        assert unresolved_but_harmless not in gaps
    assert "experience[0].start" not in gaps                 # dropped, not printed
    assert "education[0].grad_expected" not in gaps          # blocking, listed there instead


@needs_latex_gen
def test_a_profile_with_its_experience_written_builds(workspace, ashcombe_jd):
    """The refusal is about ASK, not about the wizard: fill it in and it goes."""
    from apply import generate as gen_mod

    profile = _wizard_profile(workspace)
    for key in ("experience", "projects", "skills"):
        profile.raw.pop(key, None)          # an entry you have not written yet
    assert profile.document_gaps() == []

    artifacts = gen_mod.build(profile, posting_from(ashcombe_jd), caller=FakeClaude())
    assert artifacts.ok and artifacts.letter_pdf.exists()
