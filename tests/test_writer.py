"""The write -> lint -> fit -> verify -> revise loop.

Claude is replaced by FakeClaude throughout, so these tests assert the loop's
decisions — what gets audited, what gets revised, what never becomes a PDF, and
what it costs — rather than the prose.
"""

from __future__ import annotations

import pytest

from apply import llm, writer
from apply.budget import Budget, BudgetExceeded
from conftest import posting_from


def run(profile, posting, fake, *, lint=None, fit=None, **kw):
    return writer.write(profile, posting, lint=lint or (lambda p: []), fit=fit,
                        caller=fake, **kw)


# ------------------------------------------------------------ happy path

def test_a_clean_draft_is_written_once_and_audited_once(profile, ashcombe_jd, fake_claude):
    fake = fake_claude()
    written = run(profile, posting_from(ashcombe_jd), fake)
    assert written.status == "verified" and written.ok and written.verified
    assert fake.count("Package") == 1 and fake.count("Review") == 1
    assert len(written.attempts) == 1


def test_the_cost_of_every_call_is_summed(profile, ashcombe_jd, fake_claude):
    written = run(profile, posting_from(ashcombe_jd), fake_claude())
    assert written.usage.input_tokens == 12_000          # one write, one verify
    assert written.cost > 0


# --------------------------------------------------- free checks come first

def test_a_draft_failing_the_lint_is_revised_before_anyone_pays_to_audit_it(
        profile, ashcombe_jd, fake_claude):
    bad = fake_claude.package(paragraph_2="I am passionate about data.")
    fake = fake_claude(packages=[bad, fake_claude.package()])
    lint = lambda p: ["prohibited phrase"] if "passionate" in writer.full_text(p) else []
    written = run(profile, posting_from(ashcombe_jd), fake, lint=lint)
    assert written.verified
    assert fake.count("Review") == 1                      # the bad draft was never audited
    assert fake.count("Package") == 2
    assert "prohibited phrase" in fake.calls[1][2]        # the problem went back to the writer


def test_a_draft_that_runs_to_two_pages_is_sent_back_to_be_cut(profile, ashcombe_jd, fake_claude):
    fake = fake_claude(packages=[fake_claude.package(), fake_claude.package()])
    pages = iter([2, 1])
    written = run(profile, posting_from(ashcombe_jd), fake, fit=lambda p: next(pages))
    assert written.verified
    assert "2 pages" in fake.calls[1][2]


def test_a_draft_that_never_fits_produces_nothing(profile, ashcombe_jd, fake_claude):
    written = run(profile, posting_from(ashcombe_jd), fake_claude(), fit=lambda p: 2)
    assert written.status == "refused" and not written.ok
    assert len(written.attempts) == writer.MAX_DRAFTS


# ------------------------------------------------------------ the audit

def test_an_unsupported_claim_is_sent_back_and_fixed(profile, ashcombe_jd, fake_claude):
    fake = fake_claude(reviews=[
        fake_claude.review(verdict="revise", unsupported_claims=["I led a team of five"]),
        fake_claude.review(),
    ])
    written = run(profile, posting_from(ashcombe_jd), fake)
    assert written.verified
    assert "I led a team of five" in fake.calls[2][2]     # quoted back to the writer
    assert len(written.attempts) == 2


def test_an_unsupported_claim_that_survives_every_draft_blocks_the_pdf(
        profile, ashcombe_jd, fake_claude):
    fake = fake_claude(reviews=[fake_claude.review(
        verdict="revise", unsupported_claims=["managed $4 million"])])
    written = run(profile, posting_from(ashcombe_jd), fake)
    assert written.status == "refused" and not written.ok
    assert "managed $4 million" in written.reason
    assert fake.count("Review") == writer.MAX_DRAFTS


def test_a_wrong_authorization_statement_blocks(profile, ashcombe_jd, fake_claude):
    fake = fake_claude(reviews=[fake_claude.review(verdict="revise",
                                                   authorization_correct=False)])
    assert run(profile, posting_from(ashcombe_jd), fake).status == "refused"


def test_style_findings_are_recorded_but_do_not_block(profile, ashcombe_jd, fake_claude):
    """"Correct" is the verifier's job; "good" is the owner's."""
    fake = fake_claude(reviews=[fake_claude.review(verdict="revise", findings=[
        {"severity": "should-fix", "where": "p1", "problem": "flat", "suggestion": "sharpen"},
        {"severity": "nit", "where": "p3", "problem": "long", "suggestion": "cut"},
    ])])
    written = run(profile, posting_from(ashcombe_jd), fake)
    assert written.verified
    assert len(written.findings) == 2
    assert fake.count("Package") == 1                     # no paid rewrite for taste


def test_a_blocker_finding_forces_a_revision(profile, ashcombe_jd, fake_claude):
    fake = fake_claude(reviews=[
        fake_claude.review(verdict="revise", findings=[{
            "severity": "blocker", "where": "p2", "problem": "wrong employer named",
            "suggestion": "name Ashcombe Trust"}]),
        fake_claude.review(),
    ])
    written = run(profile, posting_from(ashcombe_jd), fake)
    assert written.verified and fake.count("Package") == 2
    assert "wrong employer named" in fake.calls[2][2]


# ----------------------------------------------------------- hand edits

def test_your_own_edits_are_audited_but_never_rewritten(profile, ashcombe_jd, fake_claude):
    fake = fake_claude(reviews=[fake_claude.review(
        verdict="revise", unsupported_claims=["something you wrote"])])
    edited = fake_claude.package(paragraph_1="My own opening.")
    written = run(profile, posting_from(ashcombe_jd), fake,
                  first_draft=edited, max_drafts=1)
    assert fake.count("Package") == 0                     # nothing was written over them
    assert written.status == "refused"
    assert written.package.paragraph_1 == "My own opening."


def test_without_an_audit_a_passing_draft_is_labelled_unverified(profile, ashcombe_jd,
                                                                 fake_claude):
    fake = fake_claude()
    written = run(profile, posting_from(ashcombe_jd), fake,
                  first_draft=fake_claude.package(), max_drafts=1, verify=False)
    assert written.status == "unverified" and written.ok and not written.verified
    assert fake.calls == []


# ------------------------------------------------------------- failure

def test_no_credential_is_reported_not_raised(profile, ashcombe_jd):
    def unavailable(**_):
        raise llm.LLMUnavailable("no key")
    written = run(profile, posting_from(ashcombe_jd), unavailable)
    assert written.status == "unavailable" and "no key" in written.reason


def test_the_budget_is_checked_before_every_call(profile, ashcombe_jd, fake_claude, conn):
    budget = Budget(conn, caps={"per_call_usd": 0.0001, "per_run_usd": 5, "monthly_usd": 5})
    with pytest.raises(BudgetExceeded):
        run(profile, posting_from(ashcombe_jd), fake_claude(), budget=budget)


def test_every_call_lands_in_the_ledger(profile, ashcombe_jd, fake_claude, conn):
    budget = Budget(conn)
    fake = fake_claude(reviews=[
        fake_claude.review(verdict="revise", unsupported_claims=["x"]),
        fake_claude.review()])
    run(profile, posting_from(ashcombe_jd), fake, budget=budget)
    purposes = {purpose: calls for purpose, _, calls in budget.by_purpose()}
    assert purposes == {"write": 1, "revise": 1, "verify": 2}


# ------------------------------------------------------------- prompts

def test_the_writer_is_told_the_owner_s_default_proof_asset(profile, quillon_jd):
    _, user = writer.prompts(profile, posting_from(quillon_jd), [])
    assert "Vanilla" in user


def test_the_allocator_default_is_not_the_quant_project(profile, ashcombe_jd):
    _, user = writer.prompts(profile, posting_from(ashcombe_jd), [])
    task = user.split("# TASK", 1)[1]
    assert "Rents and Transit" in task and "Vanilla" not in task


def test_the_writer_is_given_the_exact_authorization_statement(profile, ashcombe_jd):
    _, user = writer.prompts(profile, posting_from(ashcombe_jd), [])
    assert "Will not require employment sponsorship, now or in the future." in user


def test_source_material_is_first_and_cached_so_the_audit_reuses_it(profile, ashcombe_jd):
    system, _ = writer.prompts(profile, posting_from(ashcombe_jd), [])
    assert system[0]["text"].startswith("# SOURCE MATERIAL")
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    verifier = writer._system(profile, writer.VERIFIER_RULES)
    assert verifier[0]["text"] == system[0]["text"]       # identical prefix -> cache hit


def test_nothing_private_is_sent(profile, ashcombe_jd, workspace):
    (workspace / "data" / "profile.private.yaml").write_text(
        "identity:\n  phone: '+1 555 555 0123'\n  street_address: '1 Main St'\n"
        "education_private:\n  gpa: '3.91'\n")
    from apply.profile import Profile

    system, user = writer.prompts(Profile.load(), posting_from(ashcombe_jd), [])
    sent = " ".join(b["text"] for b in system) + user
    for private in ("555 0123", "1 Main St", "3.91"):
        assert private not in sent


def test_no_hardcoded_letter_prose_remains(profile):
    """The whole point of this change: the profile carries instructions, not sentences."""
    assert "letters" not in profile.raw
    assert "writing" in profile.raw


# ------------------------------------------------------------- truncation

_REAL_CALL = llm.call      # captured at import, before the autouse tripwire replaces it


def test_output_cut_off_mid_json_is_truncated_not_a_crash(monkeypatch):
    """The SDK parses while building the response, so hitting max_tokens
    surfaces as a pydantic ValidationError. It must become an ordinary
    unavailable result, with a cost attached."""
    import pydantic

    class Messages:
        def parse(self, **kw):
            pydantic.TypeAdapter(int).validate_json('"cut off mid-str')

    class Client:
        beta = type("Beta", (), {"messages": Messages()})()

    monkeypatch.setattr(llm, "_client", lambda: Client())
    with pytest.raises(llm.Truncated) as caught:
        _REAL_CALL(system=[{"type": "text", "text": "s" * 320}], user="u" * 320,
                   schema=llm.Package, max_tokens=1000)
    assert isinstance(caught.value, llm.LLMUnavailable)
    assert caught.value.usage.output_tokens == 1000
    assert caught.value.usage.input_tokens == 200
    assert caught.value.usage.cost > 0


def test_a_truncated_call_is_charged_and_the_letter_is_unavailable(
        profile, ashcombe_jd, conn):
    budget = Budget(conn)

    def truncating(**kw):
        raise llm.Truncated("cut off", llm.Usage(model=llm.DEFAULT_MODEL,
                                                 input_tokens=5000, output_tokens=20000))

    written = run(profile, posting_from(ashcombe_jd), truncating, budget=budget)
    assert written.status == "unavailable" and not written.ok
    purposes = {purpose: calls for purpose, _, calls in budget.by_purpose()}
    assert purposes == {"write-truncated": 1}
    assert budget.month_to_date() > 0
