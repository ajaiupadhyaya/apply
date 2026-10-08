from __future__ import annotations

import json
from pathlib import Path

import pytest

from apply.setup import draft as D

FIX = Path(__file__).parent / "fixtures" / "setup"
SOURCES = (FIX / "resume.txt").read_text(encoding="utf-8")


def answers(**kw):
    base = dict(roles="backend software engineering", job_types=["internship", "full-time"],
                locations=["Seattle, WA"], remote_ok=True, firms=["Acme Robotics"], avoid="sales",
                links={"github": "https://github.com/jreyes-example"}, extra="",
                work_authorized=True, sponsorship_now=False, sponsorship_future=False,
                grad_expected="2027-05", student=True, availability_full_time=None,
                availability_internship="summer 2026")
    base.update(kw)
    return D.Answers(**base)


def canned() -> D.Draft:
    return D.Draft.model_validate(json.loads((FIX / "draft.json").read_text(encoding="utf-8")))


def test_grounding_drops_an_invented_figure_and_an_invented_employer():
    d = canned()
    d.experience[0].bullets.append("Grew revenue 300% in a quarter")
    d.experience.append(D.Experience(org="Globex", title="Intern", start="2024-06", end="2024-08",
                                     location="", bullets=["x"], detail=[], tags=[]))
    cleaned, notes = D.ground(d, SOURCES, answers())
    assert all("300%" not in b for b in cleaned.experience[0].bullets)
    assert [e.org for e in cleaned.experience] == ["Acme Robotics"]
    assert any("Globex" in n for n in notes) and any("300%" in n for n in notes)


def test_grounding_keeps_a_date_whose_year_is_sourced_and_asks_for_one_that_is_not():
    d = canned()
    cleaned, _ = D.ground(d, SOURCES, answers())
    assert cleaned.experience[0].start == "2025-06"
    d.experience[0].start = "2019-01"
    cleaned, _ = D.ground(d, SOURCES, answers())
    assert cleaned.experience[0].start == "ASK"


def test_grounding_removes_an_unsourced_link():
    d = canned()
    d.projects[0].url = "https://kestrel.example.com"
    cleaned, notes = D.ground(d, SOURCES, answers())
    assert cleaned.projects[0].url is None and any("link" in n for n in notes)


def test_grounding_keeps_the_sourced_link_and_does_not_touch_the_input():
    d = canned()
    cleaned, notes = D.ground(d, SOURCES, answers())
    assert cleaned.projects[0].url == "https://github.com/jreyes-example/kestrel"
    assert notes == []
    d.projects[0].url = "https://kestrel.example.com"
    D.ground(d, SOURCES, answers())
    assert d.projects[0].url == "https://kestrel.example.com"


def test_authorization_and_graduation_come_from_answers_not_the_model():
    files = D.to_files(canned(), answers(work_authorized=False, sponsorship_future=True))
    auth = files["profile.yaml"]["authorization"]
    assert auth["us_work_authorized"] is False and auth["requires_sponsorship_future"] is True
    assert auth["requires_sponsorship_now"] is False
    current = [e for e in files["profile.yaml"]["education"] if e.get("current")][0]
    assert current["grad_expected"] == "2027-05"


def test_profile_yaml_keeps_the_personas_essay_keys_and_drops_its_facts():
    profile = D.to_files(canned(), answers())["profile.yaml"]
    assert profile["essays"] and all(v is None for v in profile["essays"].values())
    assert "why_finance_200w" in profile["essays"]
    assert set(profile["writing"]["letter"]["proof_asset"]) == {"swe"}
    assert "_note" not in profile
    text = json.dumps(profile)
    assert "Mercer" not in text and "Vanilla" not in text


def test_search_yaml_is_valid_and_complete():
    from apply import search
    files = D.to_files(canned(), answers())
    s = files["search.yaml"]
    for key in ("rejects", "geography", "role_fit", "timing", "title_timing", "tracks", "limits", "country"):
        assert key in s, key
    merged, sources = search._merge(search.yaml.safe_load(search.DEFAULTS.read_text(encoding="utf-8")), s)
    cfg = search.build(merged, sources)
    assert [t.name for t in cfg.tracks] == ["swe"] and cfg.limits["max_years_experience"] == 2
    assert cfg.geography[0][1] == "Seattle"
    assert set(cfg.rejects) == {"seniority", "off_function", "too_technical"}
    assert cfg.rejects["seniority"].search("Senior Software Engineer")
    assert dict(cfg.role_fit) and cfg.country == "us"


def test_private_keys_are_only_the_wizards_own():
    files = D.to_files(canned(), answers(phone="(555) 201-4477", gpa="3.8"))
    private = files["profile.private.yaml"]
    assert private["identity"]["phone"] == "(555) 201-4477"
    assert private["education_private"]["gpa"] == "3.8"
    assert private["identity"]["street_address"] == "ASK"
    assert "201-4477" not in json.dumps(files["profile.yaml"])


def test_files_load_as_a_profile(workspace):
    import yaml
    from apply.profile import Profile
    files = D.to_files(canned(), answers())
    data = workspace / "data"
    (data / "profile.yaml").write_text(yaml.safe_dump(files["profile.yaml"], sort_keys=False), encoding="utf-8")
    p = Profile.load()
    assert p.display_name.endswith("Reyes") and "swe" in p.projects["kestrel"].tracks


def test_request_goes_through_llm_call_and_the_ledger(monkeypatch, conn):
    from apply import llm
    from apply.budget import Budget
    seen = {}

    def fake_call(*, system, user, schema, model, effort, **kw):
        seen.update(schema=schema, user=user)
        return canned(), llm.Usage(model, input_tokens=40000, output_tokens=9000)

    monkeypatch.setattr(llm, "call", fake_call)
    budget = Budget(conn)                              # default $0.50 per call
    result = D.request(SOURCES, answers(phone="(555) 201-4477", street_address="12 Elm St",
                                        gpa="3.8"),
                       note="more weight on Seattle", budget=budget)
    assert seen["schema"] is D.Draft and "more weight on Seattle" in seen["user"]
    assert "201-4477" not in seen["user"]               # private answers never sent
    assert "12 Elm St" not in seen["user"] and "3.8" not in seen["user"]
    assert result.identity.legal_last == "Reyes"
    assert [row[0] for row in budget.by_purpose()] == ["setup"]


def test_fake_claude_routes_other_schemas_by_name(fake_claude):
    from apply import llm
    fake = fake_claude(others={"Draft": [canned()]})
    result, _ = fake(system=[], user="u", schema=D.Draft, model=llm.DEFAULT_MODEL,
                     effort="medium", max_tokens=1000)
    assert result.identity.legal_last == "Reyes" and fake.count("Draft") == 1
    with pytest.raises(AssertionError, match="nothing scripted for Identity"):
        fake(system=[], user="u", schema=D.Identity, model=llm.DEFAULT_MODEL, effort="medium")


# ------------------------------------------------ grounding without figures

def test_grounding_drops_an_invented_skill_and_stack_item():
    d = canned()
    d.skills[0].items.append("Kubernetes")
    d.projects[0].stack.append("Rust")
    cleaned, notes = D.ground(d, SOURCES, answers())
    assert cleaned.skills[0].items == ["Python", "OCaml", "SQL"]
    assert cleaned.projects[0].stack == ["OCaml"]
    assert any("Kubernetes" in n for n in notes) and any("Rust" in n for n in notes)


def test_grounding_drops_an_invented_project():
    d = canned()
    d.projects.append(d.projects[0].model_copy(update={"key": "falcon", "name": "Falcon", "url": None}))
    cleaned, notes = D.ground(d, SOURCES, answers())
    assert [p.key for p in cleaned.projects] == ["kestrel"] and any("Falcon" in n for n in notes)


def test_grounding_checks_education():
    d = canned()
    d.education[0].degree = "M.S."
    d.education.append(D.Education(institution="Harvard University", degree="B.A."))
    cleaned, notes = D.ground(d, SOURCES, answers())
    assert [e.institution for e in cleaned.education] == ["Blue Ridge University"]
    assert cleaned.education[0].degree == "ASK" and cleaned.education[0].major == "Computer Science"
    assert any("Harvard" in n for n in notes) and any("M.S." in n for n in notes)


def test_grounding_asks_for_an_inflated_title():
    d = canned()
    d.experience[0].title = "Senior Software Engineer"
    cleaned, notes = D.ground(d, SOURCES, answers())
    assert cleaned.experience[0].title == "ASK" and any("Senior Software Engineer" in n for n in notes)


def test_grounding_asks_for_an_unsourced_name_and_email():
    d = canned()
    d.identity.legal_last = "Reynolds"
    d.identity.email = "jordan@example.com"
    cleaned, _ = D.ground(d, SOURCES, answers())
    assert cleaned.identity.legal_first == "Jordan"
    assert cleaned.identity.legal_last == "ASK" and cleaned.identity.email == "ASK"


def test_grounding_matches_whole_words_only():
    d = canned()
    d.experience[0].org = "Acme"                        # sourced: "Acme Robotics"
    d.experience.append(D.Experience(org="Meta", title="Intern", start="ASK", end="ASK",
                                     bullets=[]))
    cleaned, _ = D.ground(d, SOURCES + "\nmetadata pipelines", answers())
    assert [e.org for e in cleaned.experience] == ["Acme"]


def test_a_correction_note_is_a_source():
    d = canned()
    d.skills[0].items.append("Kubernetes")
    cleaned, notes = D.ground(d, SOURCES, answers(), note="I also use Kubernetes daily")
    assert "Kubernetes" in cleaned.skills[0].items and notes == []


# ------------------------------------------------ search.yaml that loads

def _build(files):
    from apply import search
    base = search.yaml.safe_load(search.DEFAULTS.read_text(encoding="utf-8"))
    return search.build(*search._merge(base, files["search.yaml"]))


def test_track_names_are_normalised_and_an_unknown_default_falls_back():
    d = canned()
    d.tracks[0].name = " SWE "
    d.projects[0].tracks = ["SWE"]
    d.default_track = "engineering"
    files = D.to_files(d, answers())
    cfg = _build(files)
    assert [t.name for t in cfg.tracks] == ["swe"] and cfg.default_track == "swe"
    assert files["profile.yaml"]["projects"]["kestrel"]["tracks"] == ["swe"]
    assert set(files["profile.yaml"]["writing"]["letter"]["proof_asset"]) == {"swe"}


def test_the_schema_refuses_a_bad_resume_layout_and_no_tracks():
    from pydantic import ValidationError
    raw = json.loads((FIX / "draft.json").read_text(encoding="utf-8"))
    with pytest.raises(ValidationError):
        D.Draft.model_validate({**raw, "tracks": [{**raw["tracks"][0], "resume": "skills_first"}]})
    with pytest.raises(ValidationError):
        D.Draft.model_validate({**raw, "tracks": []})


def test_drafted_rejects_keep_the_defaults_guards():
    d = canned()
    d.reject_seniority = ["senior"]
    d.reject_functions = ["sales"]
    cfg = _build(D.to_files(d, answers()))
    assert not cfg.rejects["seniority"].search("Rising Senior Summer Analyst")
    assert cfg.rejects["seniority"].search("Senior Analyst")
    assert not cfg.rejects["off_function"].search("Sales and Trading Summer Analyst")
    assert cfg.rejects["off_function"].search("Inside Sales Representative")


def test_no_remote_block_when_remote_is_not_ok():
    files = D.to_files(canned(), answers(remote_ok=False))
    assert list(files["search.yaml"]["geography"]) == ["seattle"]
    assert len(_build(files).geography) == 1
