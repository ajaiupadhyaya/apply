from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from apply.setup import wizard

FIX = Path(__file__).parent / "fixtures" / "setup"


class Script:
    """A scripted Asker. Each answer is keyed by a substring unique to one
    prompt; every scripted answer must be asked for."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.said: list[str] = []

    def _next(self, prompt):
        for i, (needle, value) in enumerate(self.answers):
            if needle.lower() in prompt.lower():
                return self.answers.pop(i)[1]
        raise AssertionError(f"unscripted prompt: {prompt!r}")

    def text(self, prompt, default=None): return self._next(prompt)
    def secret(self, prompt): return self._next(prompt)
    def confirm(self, prompt, default=True): return self._next(prompt)
    def choice(self, prompt, options, default=None): return self._next(prompt)
    def edit(self, text): return None
    def say(self, markup): self.said.append(markup)


@pytest.fixture
def fake_api(monkeypatch):
    from apply import llm, resolve, secrets
    from apply.setup import draft as D

    stored = {}
    sent: list[str] = []
    monkeypatch.setattr(secrets, "store", lambda n, v: stored.__setitem__(n, v.strip()))
    monkeypatch.setattr(secrets, "lookup", lambda n: stored.get(n))
    monkeypatch.setattr(llm, "ping", lambda: None)
    canned = D.Draft.model_validate(json.loads((FIX / "draft.json").read_text(encoding="utf-8")))

    def call(**k):
        sent.append(k["user"])
        return canned, llm.Usage(k["model"], input_tokens=5000, output_tokens=2000)

    monkeypatch.setattr(llm, "call", call)
    monkeypatch.setattr(resolve, "probe_slugs", lambda name, verify_fn=None: None)
    stored["_sent"] = sent
    return stored


def full_script(resume: Path):
    return [
        ("anthropic api key", "sk-ant-test"), ("monthly spending", "10"),
        ("kinds of roles", "backend software engineering"),
        ("internship, full-time, or both", "both"), ("where, most wanted first", "Seattle, WA"),
        ("is remote ok", True), ("firms you most want", "Acme Robotics"), ("to avoid", "sales"),
        ("linkedin url", ""), ("github url", ""), ("portfolio url", ""),
        ("should know about you", ""),
        ("authorized to work", True), ("sponsorship now", False), ("sponsorship in the future", False),
        ("currently a student", True), ("graduation date", "2027-05"),
        ("available full-time", ""), ("internship availability", "summer 2026"),
        ("phone, for your resume", "(555) 201-4477"), ("street address", ""), ("gpa", ""),
        ("path to your resume", str(resume)), ("path to a cover letter", ""), ("path to other writing", ""),
        ("identity: accept", "accept"), ("experience: accept", "accept"), ("projects: accept", "accept"),
        ("skills: accept", "accept"), ("writing: accept", "accept"), ("search: accept", "accept"),
        ("use greenhouse:acmerobotics for acme robotics (12 open postings)", True),
        ("job-alert mail", False), ("phone via ntfy", False), ("every morning", False),
    ]


def _resume(data: Path) -> Path:
    resume = data.parent / "resume.txt"
    resume.write_text((FIX / "resume.txt").read_text(encoding="utf-8"), encoding="utf-8")
    return resume


def _with_draft(data: Path) -> None:
    draft = (FIX / "draft.json").read_text(encoding="utf-8")
    (data / ".setup_draft.json").write_text(draft, encoding="utf-8")


def _probe_finds_acme(monkeypatch):
    from apply import resolve

    def probe(name, verify_fn=None):
        if name != "Acme Robotics":
            return None
        return resolve.Candidate(ats="greenhouse", evidence="probed", config={"board": "acmerobotics"},
                                 supported=True), 12

    monkeypatch.setattr(resolve, "probe_slugs", probe)


def test_a_full_run_writes_exactly_the_expected_files(isolated_data_dir, fake_api, monkeypatch):
    data = isolated_data_dir
    _probe_finds_acme(monkeypatch)
    asker = Script(full_script(_resume(data)))
    wizard.run_wizard(asker, data=data)
    assert asker.answers == []
    assert fake_api["ANTHROPIC_API_KEY"] == "sk-ant-test"
    profile = yaml.safe_load((data / "profile.yaml").read_text(encoding="utf-8"))
    private = yaml.safe_load((data / "profile.private.yaml").read_text(encoding="utf-8"))
    search = yaml.safe_load((data / "search.yaml").read_text(encoding="utf-8"))
    employers = yaml.safe_load((data / "employers.yaml").read_text(encoding="utf-8"))
    assert profile["identity"]["legal_last"] == "Reyes"
    assert private["identity"]["phone"] == "(555) 201-4477"
    assert private["budget"]["monthly_usd"] == 10.0
    assert "targets" not in private                      # the example's invented firms
    assert "swe" in search["tracks"]["kinds"]
    assert employers["employers"] == [{"name": "Acme Robotics", "ats": "greenhouse",
                                       "board": "acmerobotics", "tracks": ["swe"], "priority": 1}]
    context = (data / "context" / "resume.md").read_text(encoding="utf-8")
    assert "201-4477" not in context and context.startswith("<!-- source: resume.txt")
    every_byte = "".join(p.read_text(encoding="utf-8", errors="ignore") for p in data.rglob("*") if p.is_file())
    assert "sk-ant" not in every_byte
    # The one request sent the documents, never the phone.
    assert len(fake_api["_sent"]) == 1 and "201-4477" not in fake_api["_sent"][0]
    # Every step done; a re-run only says the closing words.
    state = json.loads((data / ".setup_state.json").read_text(encoding="utf-8"))
    assert state["done"] == list(wizard.STEPS)
    again = Script([])
    wizard.run_wizard(again, data=data)
    assert any("never submits" in s.lower() for s in again.said)


def test_a_declined_board_falls_through_to_the_careers_page(isolated_data_dir, fake_api, monkeypatch):
    from apply import resolve

    _probe_finds_acme(monkeypatch)
    asked = []

    def fake_resolve(url, *, check=True, name="probe"):
        asked.append((url, name))
        return [(resolve.Candidate(ats="lever", evidence="x", config={"board": "acme"}, supported=True), 7)]

    monkeypatch.setattr(resolve, "resolve", fake_resolve)
    _with_draft(isolated_data_dir)
    asker = Script([("use greenhouse:acmerobotics", False),
                    ("careers page for acme robotics", "https://acme.example/careers")])
    wizard.run_wizard(asker, step="employers", data=isolated_data_dir)
    assert asker.answers == []
    assert asked == [("https://acme.example/careers", "Acme Robotics")]
    employers = yaml.safe_load((isolated_data_dir / "employers.yaml").read_text(encoding="utf-8"))
    assert employers["employers"][0]["ats"] == "lever"


def test_an_unresolved_firm_is_explained_not_written(isolated_data_dir, fake_api):
    _with_draft(isolated_data_dir)
    asker = Script([("careers page for acme robotics", "")])
    wizard.run_wizard(asker, step="employers", data=isolated_data_dir)
    employers = yaml.safe_load((isolated_data_dir / "employers.yaml").read_text(encoding="utf-8"))
    assert employers["employers"] == []
    assert any("apply add --clipboard" in s for s in asker.said)


def test_a_rejected_key_is_asked_for_again(isolated_data_dir, fake_api, monkeypatch):
    from apply import llm, secrets

    def ping():
        if secrets.lookup("ANTHROPIC_API_KEY") == "sk-ant-bad":
            raise llm.LLMUnavailable("the API key was rejected.")

    monkeypatch.setattr(llm, "ping", ping)
    asker = Script([("anthropic api key", "sk-ant-bad"), ("anthropic api key", "sk-ant-good"),
                    ("monthly spending", "")])
    wizard.run_wizard(asker, step="key", data=isolated_data_dir)
    assert fake_api["ANTHROPIC_API_KEY"] == "sk-ant-good"
    assert any("rejected" in s for s in asker.said)


def test_free_text_refuses_ssn():
    asker = Script([("kinds of roles", "analyst, my SSN is 123-45-6789"), ("kinds of roles", "analyst")])
    assert wizard._ask_clean(asker, "What kinds of roles are you after?") == "analyst"
    assert any("never stores" in s.lower() for s in asker.said)


def test_setup_backs_up_existing_files(isolated_data_dir):
    (isolated_data_dir / "profile.yaml").write_text("mine: true\n", encoding="utf-8")
    wizard._write_file(isolated_data_dir, "profile.yaml", "new: true\n", Script([("replace it", True)]))
    backups = list((isolated_data_dir / ".backup").rglob("profile.yaml"))
    assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == "mine: true\n"


def test_declining_the_overwrite_keeps_the_file(isolated_data_dir):
    (isolated_data_dir / "profile.yaml").write_text("mine: true\n", encoding="utf-8")
    wizard._write_file(isolated_data_dir, "profile.yaml", "new: true\n", Script([("replace it", False)]))
    assert (isolated_data_dir / "profile.yaml").read_text(encoding="utf-8") == "mine: true\n"


def test_example_employers_are_replaced_silently(isolated_data_dir):
    from apply.setup import EXAMPLE_PROFILE
    example = EXAMPLE_PROFILE.parent / "employers.example.yaml"
    (isolated_data_dir / "employers.yaml").write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    assert wizard._write_file(isolated_data_dir, "employers.yaml", "employers: []\n", Script([]), example=example)
    assert (isolated_data_dir / "employers.yaml").read_text(encoding="utf-8") == "employers: []\n"


def test_one_step_can_be_rerun(isolated_data_dir, fake_api):
    wizard.run_wizard(Script([("anthropic api key", "sk-ant-2"), ("monthly spending", "")]),
                      step="key", data=isolated_data_dir)
    assert fake_api["ANTHROPIC_API_KEY"] == "sk-ant-2"


def test_unknown_step_exits(isolated_data_dir):
    with pytest.raises(SystemExit):
        wizard.run_wizard(Script([]), step="nope", data=isolated_data_dir)


def test_cli_quick_keeps_the_nine_questions():
    from apply.cli import app
    result = CliRunner().invoke(app, ["setup", "--help"])
    assert "--quick" in result.output and "--step" in result.output


def test_review_keeps_private_values_the_user_did_not_restate(isolated_data_dir, fake_api):
    """A blank phone answer is ASK in the draft; it must not erase a phone on
    file, nor reset a ceiling the owner raised."""
    data = isolated_data_dir
    on_file = "identity:\n  phone: '+1 555 0100 222'\nbudget:\n  per_call_usd: 1.0\n"
    (data / "profile.private.yaml").write_text(on_file, encoding="utf-8")
    _with_draft(data)
    answers = {"roles": "swe", "job_types": ["internship"], "locations": ["Seattle, WA"],
               "remote_ok": True, "firms": [], "avoid": "", "links": {}, "extra": "",
               "work_authorized": True, "sponsorship_now": False, "sponsorship_future": False,
               "grad_expected": "2027-05", "student": True, "availability_full_time": None,
               "availability_internship": None}
    state = json.dumps({"done": [], "answers": answers})
    (data / ".setup_state.json").write_text(state, encoding="utf-8")
    script = [(f"{s}: accept", "accept") for s in ("identity", "experience", "projects", "skills",
                                                   "writing", "search")]
    asker = Script(script + [("profile.private.yaml already exists", True)])
    wizard.run_wizard(asker, step="review", data=data)
    assert asker.answers == []
    private = yaml.safe_load((data / "profile.private.yaml").read_text(encoding="utf-8"))
    assert private["identity"]["phone"] == "+1 555 0100 222"
    assert private["budget"]["per_call_usd"] == 1.0
    assert private["budget"]["monthly_usd"] == 15.0
