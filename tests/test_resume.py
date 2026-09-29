"""The tailored resume and the formal register.

Claude writes each resume's bullets and project lines for the posting in the
same request as the letter; titles, employers and dates still come from the
profile. These tests assert the deterministic half: what the lint rejects, what
the resume check rejects, and what reaches the PDF.
"""

from __future__ import annotations

import shutil

import pytest

from apply import generate, writer
from apply.generate import lint, register_errors, resume_problems
from conftest import FakeClaude, posting_from

needs_latex = pytest.mark.skipif(
    shutil.which("pdflatex") is None, reason="pdflatex is not installed")


# ------------------------------------------------------------- register

@pytest.mark.parametrize("sentence", [
    "I'm applying for the Analyst role.",
    "I’d point to the engine I wrote.",
    "Quoted rates aren't comparable across providers.",
    "It's the work I want to do.",
    "That's what I want to learn.",
    "I'll bring the same care to the desk.",
    "I've built the risk half of that sentence.",
])
def test_a_contraction_fails_the_lint(profile, ashcombe_jd, sentence):
    result = lint(sentence, profile, posting_from(ashcombe_jd))
    assert any("contraction" in e for e in result.errors)


@pytest.mark.parametrize("sentence", [
    "The firm's Investment Committee sets the allocation.",
    "The posting asks for someone who \"won't stop at the first answer.\"",
    "I am applying for the Investment Intern role.",
])
def test_possessives_quotations_and_formal_prose_pass(sentence):
    assert register_errors(sentence) == []


@pytest.mark.parametrize("phrase", ["a lot of", "stuff", "kind of", "basically"])
def test_colloquial_phrasing_fails_the_lint(phrase):
    assert register_errors(f"The role involves {phrase} data work.")


def test_the_writer_is_told_the_register_is_not_negotiable(profile, ashcombe_jd):
    system, _ = writer.prompts(profile, posting_from(ashcombe_jd), [])
    rules = system[1]["text"]
    assert "No contractions" in rules
    assert "may never make it less formal" in rules
    assert "REGISTER" in writer.VERIFIER_RULES and "blocker" in writer.VERIFIER_RULES


# ------------------------------------------------------ the resume's shape

def test_the_clean_package_has_a_well_formed_resume(profile):
    assert resume_problems(FakeClaude.package(), profile) == []


def test_every_experience_entry_must_be_covered(profile):
    package = FakeClaude.package(resume_experience=[])
    assert any("no bullets for experience entry 1" in p
               for p in resume_problems(package, profile))


@pytest.mark.parametrize("bullets,expected", [
    (["Assemble panel datasets."], "has 1 bullets"),
    (["Assemble panel datasets.", "I wrote the data appendix."], "first person"),
    (["Assemble panel datasets.", " ".join(["word"] * 31)], "31 words"),
])
def test_a_bullet_that_is_not_a_resume_bullet_is_caught(profile, bullets, expected):
    package = FakeClaude.package(resume_experience=[dict(entry=1, bullets=bullets)])
    assert any(expected in p for p in resume_problems(package, profile))


def test_an_invented_entry_or_project_is_caught(profile):
    package = FakeClaude.package(
        resume_experience=[*FakeClaude.package().resume_experience,
                           dict(entry=2, bullets=["Led a desk.", "Ran a book."])],
        resume_projects=[dict(key="moonshot", line="A project that does not exist.")],
    )
    problems = resume_problems(package, profile)
    assert any("entry 2 does not exist" in p for p in problems)
    assert any('no project with the key "moonshot"' in p for p in problems)


def test_the_verifier_reads_the_resume_under_its_real_labels(profile):
    draft = writer.render_draft(FakeClaude.package(), profile)
    assert "## Resume" in draft
    assert "Research Assistant, Example University" in draft
    assert "Rents and Transit: Study of advertised rents" in draft


def test_resume_text_is_linted_with_the_letter():
    package = FakeClaude.package(resume_projects=[dict(key="vanilla", line="Pricing stuff.")])
    assert "Pricing stuff." in writer.full_text(package)


# ------------------------------------------------------------ rendering

def test_the_resume_prints_the_tailored_bullets_and_only_the_chosen_projects(profile):
    package = FakeClaude.package(resume_projects=[
        dict(key="vanilla", line="Options-pricing library tailored for this desk.")])
    tex, _ = generate.render_resume(profile, "resume_traditional", package)
    assert "Drafted the data appendix for a working paper" in tex
    assert "tailored for this desk" in tex
    assert "Rents and Transit" not in tex
    # Facts still come from the profile.
    assert "Research Assistant" in tex and "Example University" in tex


def test_without_tailored_content_the_profile_wording_is_printed(profile):
    tex, _ = generate.render_resume(profile, "resume_traditional")
    assert "Assemble and document panel datasets" in tex
    assert "Rents and Transit" in tex and "Vanilla" in tex


# ------------------------------------------------------------- the loop

def test_a_resume_over_one_page_is_sent_back(profile, ashcombe_jd, fake_claude):
    pages = iter([2, 1])
    fake = fake_claude()
    written = writer.write(profile, posting_from(ashcombe_jd), lint=lambda p: [],
                           resume_fit=lambda p: next(pages), caller=fake)
    assert written.verified
    assert fake.count("Package") == 2
    assert "resume compiles to 2 pages" in written.attempts[0].problems[0]


@needs_latex
def test_build_writes_the_tailored_resume_and_reads_it_back(profile, ashcombe_jd):
    posting = posting_from(ashcombe_jd)
    artifacts = generate.build(profile, posting, caller=FakeClaude())
    assert artifacts.ok and artifacts.resume_pdf.exists()
    assert "Drafted the data appendix" in artifacts.resume_tex.read_text()

    saved = artifacts.directory / generate.RESUME_FILE
    assert saved.exists()
    reread = generate.package_from_files(artifacts.directory)
    assert reread.resume_experience == FakeClaude.package().resume_experience


@needs_latex
def test_an_informal_draft_is_revised_and_never_printed_as_written(profile, ashcombe_jd):
    casual = FakeClaude.package(closing=(
        "I am authorized to work in the United States and will not require "
        "sponsorship, now or in the future. Happy to talk, and I'd welcome it."))
    fake = FakeClaude(packages=[casual, FakeClaude.package()])
    artifacts = generate.build(profile, posting_from(ashcombe_jd), caller=fake)
    assert artifacts.ok
    assert fake.count("Package") == 2
    assert "I'd" not in artifacts.letter_tex.read_text()
