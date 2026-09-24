"""The front door: a stranger's first ten minutes.

Two things are tested here. The persona has to be a complete, obviously
fictional person — complete because the pipeline has to run end to end on a
fresh clone, fictional because this repository is public. And the wizard has to
turn nine answers into a profile that inherits the persona's *shape* without
inheriting one fact about the persona's life.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

from apply import setup
from apply.profile import ASK, Profile


def _profile(data: dict) -> Profile:
    """Profile takes its source paths too; nothing here has any."""
    return Profile(data, [])


def persona_brief() -> dict:
    return yaml.safe_load(setup.EXAMPLE_PROFILE.read_text())["writing"]


def test_the_persona_is_a_complete_profile():
    data = yaml.safe_load(setup.EXAMPLE_PROFILE.read_text())
    profile = _profile(data)
    assert profile.unresolved() == []          # nothing left as ASK
    assert data["education"][0]["grad_expected"]
    assert data["projects"] and data["experience"]
    assert "writing" in data

    # Complete enough to write a letter on every track.
    assert profile.display_name and profile.email
    for track in ("quant", "banking", "allocator", "corporate"):
        assert profile.projects_for(track), f"no project cites the {track} track"


#: Fragments of the author's own biography. The repository is public, and the
#: first version of it shipped his profile; these are the strings that were in
#: it. A file that describes a person may not contain one of them.
AUTHORS_BIOGRAPHY = (
    "ajai", "upadhyaya", "vcu", "virginia commonwealth", "university of virginia",
    "ohcamel", "richmond", "charlottesville", "bloomberg", "morningstar", "wrds",
)

def _files_describing_a_person() -> list[pathlib.Path]:
    """Every tracked file that describes a person: the persona the tool ships,
    the profile the suite loads, and the canned letter written from it.

    The leak this guards against already happened once — data/profile.yaml was
    untracked and the same biography reappeared in tests/fixtures/profile.yaml —
    so the check covers the whole set rather than the one file that was fixed.
    """
    return [setup.EXAMPLE_PROFILE,
            pathlib.Path(__file__).parent / "fixtures" / "profile.yaml",
            pathlib.Path(__file__).parent / "conftest.py"]


@pytest.mark.parametrize("path", _files_describing_a_person(),
                         ids=lambda p: p.name)
def test_no_tracked_profile_describes_a_real_person(path):
    text = path.read_text().lower()
    for fragment in AUTHORS_BIOGRAPHY:
        assert fragment not in text, f"{path.name} names {fragment!r}"


def test_the_persona_and_the_fixture_are_the_same_invented_person():
    """One fiction, not two. A second persona is a second thing to keep clean."""
    persona = yaml.safe_load(setup.EXAMPLE_PROFILE.read_text())
    fixture = yaml.safe_load(
        (pathlib.Path(__file__).parent / "fixtures" / "profile.yaml").read_text())

    assert fixture["identity"] == persona["identity"]
    assert fixture["education"] == persona["education"]
    assert list(fixture["projects"]) == list(persona["projects"])


def test_answers_become_a_profile():
    answers = setup.Answers(
        name="Rae Mercer", email="rae@example.com", school="Example University",
        degree="BSc Economics", grad_expected="2027-06", city="London",
        work="research and analysis", authorized=True, sponsorship=False,
        links={"github": "https://github.com/example"})
    data = setup.profile_from(answers)
    profile = _profile(data)                        # constructs without error

    assert profile.display_name == "Rae Mercer"
    assert profile.email == "rae@example.com"
    assert profile.location_line == "London"
    assert profile.links == {"github": "https://github.com/example"}
    assert data["education"][0]["grad_expected"] == "2027-06"
    assert data["education"][0]["institution"] == "Example University"
    assert data["authorization"]["requires_sponsorship_now"] is False
    assert profile.grad_expected == (2027, 6)

    # A dumped mapping has no comments, so the instruction is a key, and first.
    assert next(iter(data)) == "_note"
    assert "research and analysis" in data["_note"]


def test_a_city_with_a_state_keeps_both():
    answers = setup.Answers(name="Rae Mercer", city="New York, NY")
    identity = setup.profile_from(answers)["identity"]
    assert identity["location"] == {"city": "New York", "state": "NY"}


def test_the_scaffold_inherits_no_fact_about_the_persona():
    """The shape is the persona's. Not one biographical fact is."""
    answers = setup.Answers(name="Rae Mercer", email="rae@example.com",
                            school="Some College", degree="BA", city="Boston",
                            grad_expected="2028-05")
    data = setup.profile_from(answers)
    profile = _profile(data)

    assert profile.projects == {}
    assert not data["skills"]
    assert data["availability"] == {"full_time": ASK, "internship": ASK}
    assert [e["org"] for e in data["experience"]] == [ASK]
    assert all(b == ASK for b in data["experience"][0]["bullets"])

    # The writing brief is instruction, so it is inherited — except the tracks'
    # default proof assets, which name the persona's projects.
    proof = data["writing"]["letter"]["proof_asset"]
    assert set(proof) == {"quant", "banking", "allocator", "corporate"}
    assert not any(proof.values())
    assert data["writing"]["voice"] == persona_brief()["voice"]

    # Every hole is a hole `apply doctor` will name.
    unresolved = profile.unresolved()
    assert "availability.full_time" in unresolved
    assert "experience[0].org" in unresolved

    # And nothing of the persona survives anywhere in the file.
    persona = yaml.safe_load(setup.EXAMPLE_PROFILE.read_text())
    written = yaml.safe_dump(data, sort_keys=False, allow_unicode=True).lower()
    for project in persona["projects"].values():
        assert project["name"].lower() not in written
    assert persona["experience"][0]["org"].lower() not in written


def test_writing_refuses_to_overwrite(tmp_path):
    target = tmp_path / "profile.yaml"
    setup.write_profile({"identity": {"legal_first": "A"}}, target)
    with pytest.raises(FileExistsError):
        setup.write_profile({"identity": {"legal_first": "B"}}, target)
    setup.write_profile({"identity": {"legal_first": "B"}}, target, force=True)
    assert "B" in target.read_text()


def test_examples_are_copied_only_when_missing(tmp_path):
    (tmp_path / "profile.private.example.yaml").write_text("a: 1\n")
    (tmp_path / "employers.example.yaml").write_text("employers: []\n")
    (tmp_path / "employers.yaml").write_text("employers: [{name: Mine}]\n")

    created = setup.copy_examples(tmp_path)

    assert (tmp_path / "profile.private.yaml").exists()
    assert [p.name for p in created] == ["profile.private.yaml"]
    assert "Mine" in (tmp_path / "employers.yaml").read_text()   # untouched


def test_examples_can_come_from_the_checkout(tmp_path):
    """APPLY_DATA_DIR moves the live files; the examples ship with the code."""
    source, data = tmp_path / "repo", tmp_path / "elsewhere"
    source.mkdir()
    data.mkdir()
    (source / "employers.example.yaml").write_text("employers: []\n")

    created = setup.copy_examples(data, source)

    assert [p.name for p in created] == ["employers.yaml"]
    assert (data / "employers.yaml").exists()
    assert not (source / "employers.yaml").exists()


def answering(replies: dict[str, str] | None = None, asked: list | None = None):
    """A prompt function that answers by keyword and defaults on everything else.

    Every caller has to answer the graduation question, because the wizard will
    not take a blank one — which is the point of `test_a_blank_graduation_month`
    below, and the reason a stranger's first `apply discover` no longer dies.
    """
    replies = {"graduation": "2027-05", **(replies or {})}

    def prompt(question, default=""):
        if asked is not None:
            asked.append(question)
        for keyword, answer in replies.items():
            if keyword in question.lower():
                return answer
        return default

    return prompt


def test_the_wizard_asks_and_returns_answers():
    asked: list[str] = []
    answers = setup.ask(answering(
        {"name": "Rae Mercer", "email": "rae@example.com"}, asked))

    assert answers.name == "Rae Mercer" and answers.email == "rae@example.com"
    assert len(asked) >= 8
    assert answers.authorized is True and answers.sponsorship is False


def test_declining_authorization_means_sponsorship():
    answers = setup.ask(answering({"sponsorship": "n"}))
    assert answers.authorized is False and answers.sponsorship is True


def test_a_github_answer_becomes_a_link():
    answers = setup.ask(answering({"github": "https://github.com/example"}))
    assert answers.links == {"github": "https://github.com/example"}


# ------------------------------------------------ the one answer it insists on
#
# Every other answer may be left blank and filled in later, because every other
# answer is only ever printed. The graduation month is computed with: class
# standing and the eligibility window both derive from it, so a blank one used
# to be written as ASK and kill the next command in a forty-line traceback.


def test_a_blank_graduation_month_is_put_again_rather_than_written():
    asked: list[str] = []
    with pytest.raises(ValueError):
        setup.ask(answering({"graduation": ""}, asked))         # never corrected

    grad_questions = [q for q in asked if "graduation" in q.lower()]
    assert len(grad_questions) > 1, "a blank graduation month was accepted first time"
    assert "2027-05" in grad_questions[1], "the re-ask does not show the format"


def test_a_corrected_graduation_month_is_taken():
    replies = iter(["", "May 2027", "2027-05"])

    def prompt(question, default=""):
        return next(replies) if "graduation" in question.lower() else default

    assert setup.ask(prompt).grad_expected == "2027-05"


@pytest.mark.parametrize("answer", ["", "2027", "May 2027", "2027-13", "27-05", "next year"])
def test_the_gate_cannot_read_these(answer):
    assert setup.check_grad_expected(answer) is not None


@pytest.mark.parametrize("answer", ["2027-05", "2027-5", "2031-12", " 2027-01 "])
def test_the_gate_can_read_these(answer):
    assert setup.check_grad_expected(answer) is None


def test_a_wizard_that_never_gets_an_answer_raises_rather_than_loops():
    """A non-interactive caller answering the same thing forever gets an error."""
    with pytest.raises(ValueError, match="2027-05"):
        setup.profile_from(setup.ask(answering({"graduation": "soon"})))


# --------------------------------------------------- the persona, unmodified
#
# `--persona` used to load the file and dump it back out. YAML comments do not
# survive that, and the persona's comments are not decoration: the first of them
# is the only thing in the file that says Rae Mercer is not a person.


def test_the_persona_is_copied_with_its_comments(tmp_path):
    target = tmp_path / "profile.yaml"
    setup.copy_persona(target)

    written = target.read_text()
    assert written == setup.EXAMPLE_PROFILE.read_text()
    assert "does not exist" in written.splitlines()[0]
    assert sum(1 for line in written.splitlines() if line.startswith("#")) > 10


def test_copying_the_persona_refuses_to_flatten_a_profile(tmp_path):
    target = tmp_path / "profile.yaml"
    target.write_text("identity: {legal_first: Someone}\n")
    with pytest.raises(FileExistsError):
        setup.copy_persona(target)
    setup.copy_persona(target, force=True)
    assert "Mercer" in target.read_text()


def test_the_dumped_scaffold_is_still_a_dump(tmp_path):
    """The wizard's output has no comments to keep, so it keeps its `_note`."""
    data = setup.profile_from(setup.Answers(name="Rae Mercer", grad_expected="2027-05"))
    written = setup.write_profile(data, tmp_path / "profile.yaml").read_text()
    assert written.startswith("_note:")


# ------------------------------------------- the city reaches the gate, or not


def test_the_city_becomes_the_gates_primary_geography(tmp_path):
    written = setup.write_search(
        setup.Answers(city="New York, NY", work="research"), tmp_path / "search.yaml")

    config = _search_in(tmp_path)
    assert [(label, weight) for _, label, weight, _, _ in config.geography] == [
        ("New York", 25), ("remote", 10), ("US finance hub", 6)]
    assert "research" in written.read_text()          # the work answer is at least visible


def test_a_us_city_keeps_the_us_only_checks(tmp_path):
    setup.write_search(setup.Answers(city="Austin, TX"), tmp_path / "search.yaml")
    assert _search_in(tmp_path).assume_us is True


def test_a_city_that_is_not_american_switches_the_us_checks_off(tmp_path):
    setup.write_search(setup.Answers(city="London"), tmp_path / "search.yaml")

    config = _search_in(tmp_path)
    assert config.assume_us is False
    assert config.sizes["non_us"] == 0                # London is on the shipped list
    assert [label for _, label, _, _, _ in config.geography] == ["London", "remote"]


def test_a_city_that_says_nothing_about_its_country_does_not_guess(tmp_path):
    setup.write_search(setup.Answers(city="Berlin"), tmp_path / "search.yaml")
    assert _search_in(tmp_path).assume_us is False


def test_no_city_leaves_the_shipped_geography_and_says_so(tmp_path):
    written = setup.write_search(setup.Answers(), tmp_path / "search.yaml")

    assert "geography:" not in written.read_text().replace("# geography:", "")
    assert _search_in(tmp_path).sources["geography"] == "defaults"


def test_an_existing_search_is_never_overwritten(tmp_path):
    mine = tmp_path / "search.yaml"
    mine.write_text("thresholds: {pursue: 30, maybe: 10}\n")

    assert setup.write_search(setup.Answers(city="London"), mine) is None
    assert mine.read_text() == "thresholds: {pursue: 30, maybe: 10}\n"


def test_the_persona_supplies_its_own_city(tmp_path):
    """`--persona` has no answers to work from, so it reads them back out."""
    assert setup.city_of(setup.persona()) == "London"
    assert setup.city_of({"identity": {"location": {"city": ASK}}}) == ""


def _search_in(directory):
    from apply import search as search_mod

    search_mod._load_cached.cache_clear()
    return search_mod.load(directory)
