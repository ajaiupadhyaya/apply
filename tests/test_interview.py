"""apply interview: a prep pack that says nothing the paper does not back."""

from __future__ import annotations

from conftest import FakeClaude, posting_from


def _prep(**overrides):
    from apply import interview

    base = dict(
        questions=[interview.PrepQuestion(
            question="Walk me through the panel datasets you assemble.",
            why="requirement: the posting asks for careful work on investment data",
            outline="The two faculty housing studies; reconciling three public sources.")],
        stories=[interview.Story(
            title="Reconciling three sources",
            situation="Two faculty housing studies drew on three public sources.",
            task="Make the series agree before they went into a paper.",
            action="Worked out which definition each source used and documented it.",
            result="Each table in a draft traces to its source file.",
            use_for=["attention to detail", "data quality"])],
        consistency=["The letter says I reconcile series from three public sources."],
        ask=["How does the Investment Committee use the data the intern prepares?"],
        notes="",
    )
    base.update(overrides)
    return interview.Prep(**base)


def _audit(*claims):
    from apply import interview

    return interview.PrepAudit(unsupported_claims=list(claims))


def _fake(preps, audits):
    return FakeClaude(others={"Prep": preps, "PrepAudit": audits})


def test_a_clean_prep_is_written(profile, ashcombe_jd):
    from apply import interview

    fake = _fake([_prep()], [_audit()])
    result = interview.prepare(profile, posting_from(ashcombe_jd), stage="screen",
                               submitted={}, caller=fake)
    assert result.ok and result.status == "written"
    assert [c[0] for c in fake.calls] == ["Prep", "PrepAudit"]
    text = interview.render(result.prep, posting_from(ashcombe_jd), stage="screen")
    assert "Walk me through the panel datasets" in text
    assert "Reconciling three sources" in text
    assert "Questions to ask" in text


def test_an_invented_figure_is_sent_back_before_any_audit(profile, ashcombe_jd):
    from apply import interview

    invented = _prep(consistency=["I managed a $40M sleeve of the endowment."])
    fake = _fake([invented, _prep()], [_audit()])
    result = interview.prepare(profile, posting_from(ashcombe_jd), stage="screen",
                               submitted={}, caller=fake)
    assert result.ok
    assert [c[0] for c in fake.calls] == ["Prep", "Prep", "PrepAudit"]
    revision = fake.calls[1][2]
    assert "$40m" in revision.lower() and "unsourced figure" in revision


def test_unsupported_claims_that_survive_revision_mean_no_prep(profile, ashcombe_jd):
    from apply import interview

    claim = "I led a team of analysts."
    fake = _fake([_prep()], [_audit(claim)])
    result = interview.prepare(profile, posting_from(ashcombe_jd), stage="final",
                               submitted={}, caller=fake)
    assert not result.ok and result.status == "refused"
    assert any(claim in p for p in result.problems)


def test_what_was_submitted_is_a_source_and_is_in_the_request(profile, ashcombe_jd):
    from apply import interview

    body = "My appendix covered 37 adjustments."
    fake = _fake([_prep(consistency=["The letter mentions 37 adjustments."])], [_audit()])
    result = interview.prepare(profile, posting_from(ashcombe_jd), stage="technical",
                               submitted={"body.md": body}, caller=fake)
    assert result.ok
    assert body in fake.calls[0][2]
    assert "technical" in fake.calls[0][2].lower()


def test_submitted_documents_are_read_from_the_folder(tmp_path):
    from apply import interview

    (tmp_path / "body.md").write_text("letter body", encoding="utf-8")
    (tmp_path / "answers.md").write_text("portal answers", encoding="utf-8")
    (tmp_path / "PROMPT.md").write_text("not submitted", encoding="utf-8")
    docs = interview.submitted_documents(tmp_path)
    assert docs == {"body.md": "letter body", "answers.md": "portal answers"}


def test_no_credential_is_unavailable_not_a_crash(profile, ashcombe_jd):
    from apply import interview, llm

    def down(**_):
        raise llm.LLMUnavailable("no key")

    result = interview.prepare(profile, posting_from(ashcombe_jd), stage="screen",
                               submitted={}, caller=down)
    assert result.status == "unavailable" and "no key" in result.reason


def test_the_cli_writes_the_pack_and_logs_it(conn, profile, ashcombe_jd, monkeypatch):
    from typer.testing import CliRunner

    from apply import db, generate, llm
    from apply.cli import app

    posting = posting_from(ashcombe_jd)
    db.create_posting(conn, posting)
    monkeypatch.setattr(llm, "call", _fake([_prep()], [_audit()]))

    result = CliRunner().invoke(app, ["interview", posting.slug, "--stage", "superday"])
    assert result.exit_code == 0, result.output
    pack = generate.out_dir() / posting.slug / "interview-superday.md"
    assert "Walk me through the panel datasets" in pack.read_text(encoding="utf-8")
    row = db.row_for(conn, posting.slug)
    assert any("interview prep" in e.detail for e in db.events(conn, row.application.id))


def test_the_cli_refuses_an_unknown_stage(conn, profile, ashcombe_jd):
    from typer.testing import CliRunner

    from apply import db
    from apply.cli import app

    posting = posting_from(ashcombe_jd)
    db.create_posting(conn, posting)
    result = CliRunner().invoke(app, ["interview", posting.slug, "--stage", "lunch"])
    assert result.exit_code != 0


def test_the_cli_writes_nothing_when_the_audit_still_objects(conn, profile, ashcombe_jd,
                                                             monkeypatch):
    from typer.testing import CliRunner

    from apply import db, generate, llm
    from apply.cli import app

    posting = posting_from(ashcombe_jd)
    db.create_posting(conn, posting)
    monkeypatch.setattr(llm, "call", _fake([_prep()], [_audit("I led a [bold]team[/].")]))

    result = CliRunner().invoke(app, ["interview", posting.slug])
    assert result.exit_code == 1
    assert "no prep pack written" in result.output and "team" in result.output
    assert not (generate.out_dir() / posting.slug / "interview-screen.md").exists()
