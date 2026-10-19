"""apply followup --draft: a short, formal nudge, drafted and never sent."""

from __future__ import annotations

from conftest import FakeClaude, posting_from


def _note(**overrides):
    from apply import followup

    base = dict(subject="Investment Intern application",
                body=("Dear Hiring Team,\n\nI applied for the Investment Intern role at "
                      "Ashcombe Trust and remain very interested in the position. I would "
                      "welcome any update on the timeline.\n\nKind regards"),
                notes="")
    base.update(overrides)
    return followup.Note(**base)


def _audit(*claims):
    from apply import interview

    return interview.PrepAudit(unsupported_claims=list(claims))


def _fake(notes, audits=None):
    return FakeClaude(others={"Note": notes, "PrepAudit": audits or [_audit()]})


def test_a_clean_note_is_drafted(profile, ashcombe_jd):
    from apply import followup

    fake = _fake([_note()])
    result = followup.draft(profile, posting_from(ashcombe_jd), submitted_on="2026-09-01",
                            days_quiet=21, earlier=0, caller=fake)
    assert result.ok
    assert [c[0] for c in fake.calls] == ["Note", "PrepAudit"]
    assert "21 days" in fake.calls[0][2] and "2026-09-01" in fake.calls[0][2]


def test_a_casual_note_is_sent_back_by_the_lint(profile, ashcombe_jd):
    from apply import followup

    casual = _note(body="Hi! Just checking in, I'm still super excited about it.")
    fake = _fake([casual, _note()])
    result = followup.draft(profile, posting_from(ashcombe_jd), submitted_on="2026-09-01",
                            days_quiet=21, earlier=0, caller=fake)
    assert result.ok
    assert [c[0] for c in fake.calls] == ["Note", "Note", "PrepAudit"]
    assert "contraction" in fake.calls[1][2]


def test_an_unsupported_claim_that_survives_means_no_note(profile, ashcombe_jd):
    from apply import followup

    fake = _fake([_note()], [_audit("I have since completed a CFA level.")])
    result = followup.draft(profile, posting_from(ashcombe_jd), submitted_on="2026-09-01",
                            days_quiet=21, earlier=1, caller=fake)
    assert not result.ok and result.status == "refused"


def _submitted(conn, posting):
    from apply import db
    from apply.models import Status

    db.create_posting(conn, posting)
    row = db.row_for(conn, posting.slug)
    for target, via in ((Status.GENERATED, "gen"), (Status.READY, "review"),
                        (Status.SUBMITTED, "submit")):
        db.transition(conn, row.application.id, target, via=via)
    return db.row_for(conn, posting.slug)


def test_the_cli_saves_the_draft_and_sends_nothing(conn, profile, ashcombe_jd, monkeypatch):
    from typer.testing import CliRunner

    from apply import db, generate, llm
    from apply.cli import app

    posting = posting_from(ashcombe_jd)
    row = _submitted(conn, posting)
    monkeypatch.setattr(llm, "call", _fake([_note()]))

    result = CliRunner().invoke(app, ["followup", posting.slug, "--draft"])
    assert result.exit_code == 0, result.output
    assert "remain very interested" in result.output
    drafts = list((generate.out_dir() / posting.slug).glob("followup-*.md"))
    assert len(drafts) == 1
    events = db.events(conn, row.application.id)
    assert any("not sent" in (e.detail or "") for e in events)
    assert db.row_for(conn, posting.slug).application.status == "submitted"


def test_the_cli_will_not_chase_what_was_never_sent(conn, profile, ashcombe_jd):
    from typer.testing import CliRunner

    from apply import db
    from apply.cli import app

    posting = posting_from(ashcombe_jd)
    db.create_posting(conn, posting)
    result = CliRunner().invoke(app, ["followup", posting.slug, "--draft"])
    assert result.exit_code == 1
    assert "not been submitted" in result.output
