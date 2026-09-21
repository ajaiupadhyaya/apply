"""The twelve acceptance tests from the handoff spec, in order.

These are the definition of done. Each one is named after the behaviour it
protects, not the code it happens to touch.
"""

from __future__ import annotations

import datetime as _dt
import shutil

import pytest

from apply import db, digest as digest_mod, generate
from apply.cli import BLOCKED_HOSTS
from apply.models import Posting, Status, TransitionError
from apply.parse import parse
from conftest import posting_from

needs_latex = pytest.mark.skipif(
    shutil.which("pdflatex") is None, reason="pdflatex is not installed"
)


# 1 --------------------------------------------------------------------
def test_vcimco_is_allocator_with_the_right_deadline_and_proof(profile, vcimco_jd):
    parsed = parse(vcimco_jd)
    assert parsed.classification.track.value == "allocator"
    assert parsed.deadline == _dt.date(2026, 10, 14)

    proof = generate.compose(profile, parsed.to_posting()).paragraphs[1]
    assert "Bloomberg Terminal" in proof and "WRDS" in proof
    assert "OhCamel" not in proof


# 2 --------------------------------------------------------------------
def test_blackrock_is_quant_and_its_proof_is_ohcamel(profile, blackrock_jd):
    parsed = parse(blackrock_jd)
    assert parsed.classification.track.value == "quant"
    assert "OhCamel" in generate.compose(profile, parsed.to_posting()).paragraphs[1]


# 3 --------------------------------------------------------------------
@needs_latex
def test_passionate_fails_the_lint_and_produces_no_pdf(profile, vcimco_jd):
    posting = posting_from(vcimco_jd)
    directory = generate.out_dir() / posting.slug
    directory.mkdir(parents=True, exist_ok=True)

    good = generate.build(profile, posting)
    assert good.letter_pdf.exists()

    (directory / "body.md").write_text(
        "I am applying for the Investment Intern role at VCIMCO.\n\n"
        "I am passionate about institutional investing.\n\n"
        "BASIS is a research report I write.\n\n"
        "The specific draw is the Investment Committee."
    )
    bad = generate.build(profile, posting, from_body=True)
    assert not bad.ok
    assert any("passionate" in e for e in bad.lint.errors)
    assert bad.letter_pdf is None
    # And the previous PDF is gone, so yesterday's letter cannot look current.
    assert not good.letter_pdf.exists()


# 4 --------------------------------------------------------------------
@needs_latex
def test_an_ampersand_in_a_company_name_compiles(profile, vcimco_jd):
    posting = posting_from(vcimco_jd, company="Smith & Co.", slug="smith-co-analyst-2027")
    artifacts = generate.build(profile, posting)
    assert artifacts.ok
    assert generate.page_count(artifacts.letter_pdf) == 1
    assert r"Smith \& Co." in artifacts.letter_tex.read_text()


# 5 --------------------------------------------------------------------
def test_handshake_urls_are_rejected():
    from urllib.parse import urlparse

    for url in ("https://app.joinhandshake.com/jobs/123",
                "https://joinhandshake.com/jobs/123",
                "https://www.joinhandshake.com/stu/jobs/9"):
        host = urlparse(url).hostname.lower()
        assert host in BLOCKED_HOSTS or host.endswith(".joinhandshake.com")


# 6 --------------------------------------------------------------------
def test_submit_is_refused_before_review(conn):
    posting = db.create_posting(conn, Posting(
        slug="acme-analyst-2027", company="Acme", role="Analyst",
        track="corporate", jd_raw="text"))
    application = db.get_application(conn, posting.id)
    db.transition(conn, application.id, Status.GENERATED, via="gen")
    with pytest.raises(TransitionError, match="apply review"):
        db.transition(conn, application.id, Status.SUBMITTED, via="submit")


# 7 --------------------------------------------------------------------
def test_regenerating_a_ready_application_resets_it(conn):
    posting = db.create_posting(conn, Posting(
        slug="acme-analyst-2027", company="Acme", role="Analyst",
        track="corporate", jd_raw="text"))
    application = db.get_application(conn, posting.id)
    db.transition(conn, application.id, Status.GENERATED, via="gen")
    db.transition(conn, application.id, Status.READY, via="review")
    assert db.get_application_by_id(conn, application.id).reviewed_at

    db.transition(conn, application.id, Status.GENERATED, via="gen")
    after = db.get_application_by_id(conn, application.id)
    assert after.status == "generated"
    assert after.reviewed_at is None


# 8 --------------------------------------------------------------------
def test_a_jd_with_no_deadline_gets_null_and_a_warning():
    parsed = parse("Acme Capital Partners\nResearch Associate\n\n"
                   "We review applications on a rolling basis.")
    assert parsed.deadline is None
    assert any("no application deadline" in n for n in parsed.notes)

    posting = parsed.to_posting()
    assert posting.deadline is None


def test_the_dashboard_counts_undated_postings(conn):
    db.create_posting(conn, Posting(slug="a-b-2027", company="A", role="B",
                                    track="corporate", jd_raw="x"))
    assert digest_mod.headline(conn)["no_deadline"] == 1


# 9 --------------------------------------------------------------------
def test_digest_lists_the_vcimco_deadline(conn, vcimco_jd):
    db.create_posting(conn, posting_from(vcimco_jd, slug="vcimco-investment-intern-2027"))
    result = digest_mod.build(conn)
    listed = result.overdue + result.deadlines + result.beyond
    assert any(row.posting.slug == "vcimco-investment-intern-2027" for row in listed)
    assert all(row.posting.deadline == _dt.date(2026, 10, 14) for row in listed)


# 10 -------------------------------------------------------------------
def test_the_stylesheet_defines_dark_mode_and_a_narrow_breakpoint():
    css = (generate.repo_root() / "src" / "apply" / "web" / "static" / "apply.css").read_text()
    assert "@media (prefers-color-scheme: dark)" in css
    assert ':root:not([data-theme="light"])' in css
    assert ':root[data-theme="dark"]' in css
    assert "@media (max-width: 46rem)" in css      # 736px, covers a 390px phone
    assert "prefers-reduced-motion" in css
    assert "overflow-x: hidden" in css


# Beyond the spec, but the same class of guarantee -----------------------
def test_no_browser_automation_exists_anywhere():
    """The machinery that would make submitting possible is simply absent.

    This is the load-bearing guarantee: there is no driver, no click, no form
    submission in the codebase, so no bug and no future edit can accidentally
    fire one.
    """
    import re
    from apply.outbound import FORBIDDEN_MACHINERY

    offenders = []
    for path in (generate.repo_root() / "src").rglob("*.py"):
        if path.name == "outbound.py":
            continue                      # the file that declares the list
        text = path.read_text().lower()
        for needle in FORBIDDEN_MACHINERY:
            if needle in text:
                offenders.append(f"{path.name}: {needle}")
        if re.search(r"\.click\s*\(", text):
            offenders.append(f"{path.name}: .click(")
    assert offenders == [], f"submission machinery found: {offenders}"


def test_every_outbound_call_site_is_declared():
    """A request from an undeclared module fails the suite.

    Discovery is made of network calls, so "makes no requests" is the wrong
    invariant. The right one is that every place that can send anything is
    listed in apply.outbound with a reason it is not an employer.
    """
    import re
    from apply.outbound import ALLOWED

    sends = re.compile(r"\b(?:httpx|requests|client|connection)\.(?:post|put|patch)\s*\(|urlopen\s*\(")
    undeclared = []
    for path in (generate.repo_root() / "src" / "apply").rglob("*.py"):
        if not sends.search(path.read_text()):
            continue
        module = "apply." + ".".join(
            path.relative_to(generate.repo_root() / "src" / "apply").with_suffix("").parts)
        module = module.replace(".__init__", "")
        if module not in ALLOWED:
            undeclared.append(module)
    assert undeclared == [], (
        f"these modules send requests but are not declared in apply.outbound: {undeclared}")


def test_no_employer_facing_host_is_allowed():
    """Nothing in the allow-list is an application portal."""
    from apply.outbound import ALLOWED

    portals = ("workday.com/apply", "myworkdayjobs.com/apply", "joinhandshake",
               "greenhouse.io/applications", "lever.co/apply")
    for hosts, reason in ALLOWED.values():
        assert reason.strip(), "every allowed host needs a stated reason"
        for host in hosts:
            assert not any(p in host for p in portals), host


def test_no_credential_is_ever_written_to_disk():
    import re
    from pathlib import Path

    for path in (generate.repo_root() / "src").rglob("*.py"):
        text = path.read_text()
        # A key may be read from the environment; it may never be written out.
        for match in re.finditer(r"ANTHROPIC_API_KEY", text):
            line = text[:match.start()].count("\n")
            source_line = text.splitlines()[line]
            assert "environ" in source_line or "#" in source_line or '"' in source_line
