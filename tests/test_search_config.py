"""The gate's verdicts, frozen against a corpus built from the gate's own words.

`tools/synthesize_corpus.py` wrote tests/fixtures/gate_corpus.json: for every
pattern in src/apply/search.defaults.yaml, a title or a location assembled out
of that pattern, scored by the current code and frozen — plus near-misses for
the word boundaries and lookarounds a transcription would quietly drop, and a
case for each rule score.py keeps that the YAML does not configure. The
refactor that turned score.py's literals into configuration may not move a
single verdict, and this is what says so.

Nothing in it comes from a real posting. An earlier version of this corpus was
one real pipeline with the firms' names cut out, and that was not enough: a firm
is also its sub-brands, its products and its office address, and because the
employer label grouped rows, one surviving brand named every other row of that
employer. Cutting brand names one at a time is a denylist of private facts, and
a denylist of private facts is never finished. So the committed corpus is
synthetic, `test_the_committed_corpus_names_no_real_firm` keeps it that way, and
the real pipeline stays in tests/fixtures/score_corpus.local.json, which
.gitignore keeps out of the repository and which the test that uses it skips
when it is not there.

The second half of this file is the other side of the same refactor: that a
block copied into data/search.yaml really does replace the shipped one.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest
import yaml

from apply import search
from apply.score import score
from apply.sources.base import RawPosting

FIXTURES = Path(__file__).parent / "fixtures"
CORPUS = json.loads((FIXTURES / "gate_corpus.json").read_text())
CASES = CORPUS["cases"]
LOCAL = FIXTURES / "score_corpus.local.json"
REPO = Path(__file__).resolve().parents[1]
REPO_DATA = REPO / "data"

PREFERENCES = {"graduation": tuple(CORPUS["graduation"]),
               "class_standing": CORPUS["class_standing"]}

#: The gate exactly as the package ships it: no data/search.yaml anywhere in it.
#:
#: The corpus was frozen against these, so these are what it has to be replayed
#: against. A bare `score(posting)` would instead call `search.load()`, which
#: reads the data directory — and then whatever that machine happens to hold
#: rewrites the verdicts this file exists to pin. Naming the defaults is the
#: difference between a corpus that is frozen and one that is merely undisturbed.
SHIPPED = search.load(Path("/nonexistent"))


def _by_path(name: str):
    """A file in tools/, imported by path: tools/ is scripts, not a package."""
    path = REPO / "tools" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def posting_of(case: dict) -> RawPosting:
    return RawPosting(employer=case["employer"], title=case["title"], url="",
                      source="frozen", location=case["location"],
                      description=case.get("body", ""),
                      employer_priority=case["priority"],
                      employer_senior_grades=tuple(case.get("senior_grades", ())),
                      employer_tracks=tuple(case.get("tracks", ())))


def disagreements(cases: list[dict], preferences: dict | None = None) -> list[str]:
    out = []
    for case in cases:
        got = score(posting_of(case), preferences or PREFERENCES,
                    case.get("standing"), config=SHIPPED)
        if (got.value, got.verdict.value) != (case["value"], case["verdict"]):
            out.append(f"{case['title'][:48]!r}: was {case['verdict']} {case['value']}, "
                       f"now {got.verdict.value} {got.value}")
    return out


# ------------------------------------------------------- what the corpus pins


def test_the_corpus_covers_every_configured_entry():
    """Every pattern in the YAML has a case, or this fails and says which.

    The point of a corpus this size is that it is complete: not that some
    postings still score what they scored, but that every entry the gate is
    configured with still does. A new reject pattern, a retuned weight, a city
    added to `geography` — each of them arrives with no case behind it until
    `uv run python tools/synthesize_corpus.py` is run again, and until then this
    is the test that says so.
    """
    exercised = {tuple(case["entry"]) for case in CASES if case["kind"] == "entry"}
    missing = [f"{path} {pattern!r}"
               for path, pattern, _ in _by_path("synthesize_corpus").configured()
               if (path, pattern) not in exercised]

    assert missing == [], (
        f"{len(missing)} entries in search.defaults.yaml have no case in the "
        f"corpus, e.g. {missing[:3]}. Rerun tools/synthesize_corpus.py.")


def test_every_case_still_exercises_the_entry_it_names():
    """A case is only evidence about the entry it actually matches.

    Each case names the configured pattern it was built from and whether that
    pattern is supposed to match it. Edit the pattern in the YAML and the case
    built for it may quietly stop being about it — still passing, still green,
    pinning nothing. This is the check that the corpus and the configuration are
    still talking about the same thing.
    """
    synth = _by_path("synthesize_corpus")
    wrong = []
    for case in CASES:
        if case["kind"] == "algorithm":
            continue                     # a rule in score.py; no pattern to name
        path, pattern = case["entry"]
        hit = bool(synth.compiled(path, pattern).search(synth.reads(case)))
        if hit is not (case["kind"] == "entry"):
            wrong.append(f"{path} {pattern!r} {'matches' if hit else 'misses'} "
                         f"{case['title'][:40]!r}, which is filed as {case['kind']}")

    assert wrong == [], f"{len(wrong)} cases came unhooked, e.g. {wrong[:3]}"


def test_every_frozen_verdict_is_reproduced():
    wrong = disagreements(CASES)
    assert wrong == [], f"{len(wrong)} verdicts moved, e.g. {wrong[:3]}"


def test_every_frozen_verdict_keeps_its_reasons():
    """The number and the sentence under it: which rule paid, and how much."""
    wrong = []
    for case in CASES:
        got = score(posting_of(case), PREFERENCES, case.get("standing"),
                    config=SHIPPED)
        if (got.rejected_by, got.reasons) != (case["rejected_by"], case["reasons"]):
            wrong.append(f"{case['title'][:40]!r}: was {case['rejected_by']} "
                         f"{case['reasons']}, now {got.rejected_by} {got.reasons}")

    assert wrong == [], f"{len(wrong)} reasons changed, e.g. {wrong[:2]}"


def test_the_corpus_carries_both_halves_of_every_rule():
    """Positives alone cannot catch a dropped boundary; near-misses can."""
    kinds = {kind: sum(1 for case in CASES if case["kind"] == kind)
             for kind in ("entry", "near-miss", "algorithm")}

    assert kinds["entry"] > 200
    assert kinds["near-miss"] > 20
    assert kinds["algorithm"] > 15


# ------------------------------------------------ what the corpus may not carry
#
# The corpus is a public file in a public repository. The list of firms one
# person is applying to is not: .gitignore keeps the registry out of the tree,
# and a corpus that named the same firms would publish it anyway. The previous
# corpus was real postings with the registry's names cut out of them, and a gate
# review found what a denylist always leaves — sub-brands, product names, two
# office addresses — each of which named a firm, and through the employer label
# named every other row of that firm as well. This corpus is synthetic, and
# these are the tests that keep it that way.

#: What a gate review found in the corpus this one replaced. Not one of them is
#: a registry name — which is exactly why cutting registry names out left them
#: behind — and every one of them names a firm: a sub-brand, a product, an
#: office. They are written out here so that a corpus rebuilt from a real
#: pipeline fails this test rather than shipping.
LEAKED = [
    "Kinexys", "PricingDirect", "JPMC", "Cubist", "Aladdin", "BARX", "(BXMA)",
    "K-Star", "PJT Camberview", "KippsDeSanto",
    "NY7 - 50 Hudson Yards", "745 7th Avenue",
]

#: A street number and a street. A Workday location is an office, an office is
#: as good as a name, and no synthesised case has any reason to carry one — so
#: the shape is refused rather than any particular address.
STREET = re.compile(
    r"\b\d{1,4}\s+[\w.'-]+(?:\s+[\w.'-]+)?\s+"
    r"(street|st|avenue|ave|plaza|place|road|boulevard|blvd|broadway|way)\b", re.I)


def _registry_spellings() -> list[str]:
    employers = yaml.safe_load((REPO_DATA / "employers.example.yaml").read_text())
    names = []
    for entry in employers["employers"]:
        names.append(entry["name"])
        names += entry.get("aliases") or []
    return sorted({name for name in names if len(name) > 2})


def test_the_committed_corpus_names_no_real_firm():
    """Grep the fixture for anything that looks like an employer.

    Three things it must not hold: a name from the registry the repository
    ships, a brand of the kind the previous corpus leaked, or a street address.
    A reader who greps this file must come away with the vocabulary of the gate
    and nothing about anybody's search.
    """
    text = (FIXTURES / "gate_corpus.json").read_text()

    found = [name for name in _registry_spellings()
             if re.search(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])",
                          text, re.I)]
    found += [brand for brand in LEAKED if brand.lower() in text.lower()]
    address = STREET.search(text)

    assert found == [], f"the committed corpus names {found}"
    assert address is None, f"the committed corpus carries an address: {address!r}"


def test_the_corpus_says_where_it_came_from():
    """A reader should not have to diff it against a pipeline to find out."""
    assert "invented" in CORPUS["note"]
    assert "search.defaults.yaml" in CORPUS["note"]


def test_the_real_pipeline_corpus_is_not_committed():
    """It is one person's search, and it stays on their machine.

    The file may or may not exist here — `tools/freeze_scores.py` writes it and
    a fresh clone has never run that. What may not happen is for it to be
    committable when it does exist.
    """
    import shutil
    import subprocess

    if shutil.which("git") is None:                       # pragma: no cover
        pytest.skip("git is not installed")
    # The second path is the name the committed corpus used to have. A
    # freeze_scores.py from an older checkout still writes it, and it must not
    # be able to come back into the tree.
    private = ["tests/fixtures/score_corpus.local.json",
               "tests/fixtures/score_corpus.json"]
    result = subprocess.run(["git", "-C", str(REPO), "check-ignore", *private],
                            capture_output=True, text=True)

    assert sorted(set(private) - set(result.stdout.split())) == []


@pytest.mark.skipif(not LOCAL.exists(),
                    reason="no local corpus; run tools/freeze_scores.py against a live db")
def test_the_owners_own_pipeline_still_scores_the_same():
    """The other corpus: real titles and real descriptions, on one machine.

    Everything the synthetic corpus cannot be — real employers' wording, real
    locations as a job board writes them, the rules that only fire on a
    description — is checked here, against a file that is never committed. It is
    the author's re-verification, and it skips itself for everybody else.
    """
    local = json.loads(LOCAL.read_text())
    cases = [*local.get("titles", []), *local.get("bodied", [])]
    preferences = {"graduation": tuple(local["graduation"]),
                   "class_standing": local["class_standing"]}

    assert cases, "the local corpus is present but holds no cases"
    wrong = disagreements(cases, preferences)
    assert wrong == [], f"{len(wrong)} verdicts moved, e.g. {wrong[:3]}"


def test_a_users_own_search_yaml_cannot_move_the_frozen_corpus():
    """What the suite reports is the package's behaviour, not this machine's.

    `apply setup` is step one of the README's quick start, and it writes a
    data/search.yaml for the city it asked about. Every test outside the
    `workspace` fixture used to read the repository's own data directory, so a
    cloner who answered anything but "New York" got a red suite on a clean
    checkout — 753 frozen verdicts moved, because their `geography` block had
    quietly replaced the shipped one underneath this corpus. The README, two
    sections down, said what is in data/ changes nothing.

    Two things make that true now, and this fails if either is undone: the data
    directory every test sees is a temporary one (`isolated_data_dir` in
    conftest), and the corpus is replayed against `SHIPPED` rather than against
    whatever `search.load()` finds.
    """
    from apply.profile import data_dir

    data = data_dir()
    assert data.resolve() != REPO_DATA, (
        f"the data directory under test is the repository's own ({data}). "
        "Writing a search.yaml into it would edit the working tree, so the "
        "isolation in tests/conftest.py is gone — fix that, not this test.")

    (data / "search.yaml").write_text(search.starter("London"))
    search._load_cached.cache_clear()

    # The file is genuinely in force: the production loader picks it up, and it
    # is the override that used to break the corpus. Without this the test could
    # pass by writing somewhere nothing reads.
    live = search.load()
    assert live.sources["geography"] == "data/search.yaml"
    assert [g[1] for g in live.geography] == ["London", "remote"]

    wrong = disagreements(CASES)
    assert wrong == [], f"{len(wrong)} verdicts moved, e.g. {wrong[:3]}"


# ------------------------------------------------ the configuration itself
#
# The corpus above says the defaults still score what they always scored. These
# say the defaults are now only defaults: a block copied into data/search.yaml
# replaces that block, and leaves every other one alone.


def test_an_override_replaces_one_block_and_keeps_the_rest(tmp_path):
    (tmp_path / "search.yaml").write_text(
        "geography:\n"
        "  primary: {weight: 30, label: Berlin, patterns: [berlin]}\n")
    config = search.load(tmp_path)

    assert [g[1] for g in config.geography] == ["Berlin"]
    assert config.thresholds == {"pursue": 70, "maybe": 45}      # untouched
    assert config.sources["geography"] == "data/search.yaml"
    assert config.sources["role_fit"] == "defaults"
    assert len(config.role_fit) > 20                             # still the defaults


def test_the_override_changes_the_verdict(tmp_path):
    (tmp_path / "search.yaml").write_text(
        "geography:\n"
        "  primary: {weight: 30, label: Berlin, patterns: [berlin]}\n")
    config = search.load(tmp_path)
    berlin = RawPosting(employer="X", title="Research Analyst", url="", source="t",
                        location="Berlin, Germany", description="")

    assert "Berlin +30" in "; ".join(score(berlin, config=config).reasons)


def test_a_broken_override_says_which_file(tmp_path):
    (tmp_path / "search.yaml").write_text("geography: {primary: {weight: 30}}\n")
    with pytest.raises(KeyError, match="data/search.yaml"):
        search.load(tmp_path)


def test_with_no_override_every_block_comes_from_the_defaults(tmp_path):
    config = search.load(tmp_path)

    assert set(config.sources.values()) == {"defaults"}
    assert "seniority" in config.rejects
    assert config.non_us.search("London, United Kingdom")


# ------------------------------------------- what the local corpus may carry
#
# The local corpus is real postings, and the tool that writes it takes the
# firms' names out of them anyway: a corpus is easier to read when it is about
# the scorer, and a file one command away from being pasted into a bug report
# should not be a target list. The tests below are of that cutting — including
# the one it cannot do, which is why the committed corpus is not made this way.


def _freezer():
    return _by_path("freeze_scores")


@pytest.mark.parametrize("title,names,expected", [
    ("Ashcombe Academy Investment Analyst Program",
     ["Ashcombe"], "Academy Investment Analyst Program"),
    # The registry spells it one way and the posting another. Both are the
    # same disclosure, so both have to go.
    ("B.T. Wrenfield Wealth Management - Private Client Advisor",
     ["BTWrenfield"], "Wealth Management - Private Client Advisor"),
    ("Fenwold | Brindlemere - Investment Banking Internship 2027",
     ["Fenwold", "Brindlemere"], "Investment Banking Internship 2027"),
    # A firm's name inside a longer word is a coincidence, not a disclosure.
    ("2027 Investment Bank Summer Analyst Program - Product Track",
     ["Gram"], "2027 Investment Bank Summer Analyst Program - Product Track"),
    ("Investment Banking Analyst II/III (Vellum Structure Advisory)",
     ["iVellum"], "Investment Banking Analyst II/III (Vellum Structure Advisory)"),
    # A location is an office, and an office can be as good as a name.
    ("WRENFIELD PLACE FKA 3 WORLD FINANCIAL CENTER, 200 HARLOW STREET:NEW YORK",
     ["Wrenfield"], "PLACE FKA 3 WORLD FINANCIAL CENTER, 200 HARLOW STREET:NEW YORK"),
])
def test_a_firm_s_name_is_cut_out(title, names, expected):
    assert _freezer().scrub(title, names) == expected


def test_what_cutting_the_name_out_cannot_reach():
    """The reason the committed corpus is synthesised rather than scrubbed.

    The scrubber takes out the names the registry knows. It cannot take out the
    ones it does not: a firm's sub-brand, its product, the building it sits in.
    Each of those names the firm as surely as the firm's own name does, and in a
    corpus whose employer column groups rows, one of them names every other row
    of that employer too. This is that hole, demonstrated rather than asserted
    away — and it is why nothing derived from a real pipeline is committed.
    """
    scrubbed = _freezer().scrub(
        "Calderwell Multi-Asset Investing (CMAI) - Treasury, Analyst",
        ["Calderwell"])

    assert scrubbed == "Multi-Asset Investing (CMAI) - Treasury, Analyst"
    assert "CMAI" in scrubbed          # the sub-brand survives, and names the firm


def test_cutting_the_name_out_does_not_move_the_verdict():
    """The gate reads the work, not the letterhead.

    If removing a firm's name changed what a title scored, the local corpus
    could not be anonymised without falsifying it — and the gate would be
    scoring something it has no business scoring. freeze_scores refuses to write
    when this is untrue; this is the same check, on the synthetic rows.
    """
    for case in CASES[:200]:
        plain = score(posting_of(case), PREFERENCES, case.get("standing"),
                      config=SHIPPED)
        for name in ("Quillon", "Ashcombe Trust", "Fenwold Securities", "Brindlemere"):
            named = score(posting_of({**case, "title": f"{name} {case['title']}"}),
                          PREFERENCES, case.get("standing"), config=SHIPPED)
            assert (named.value, named.verdict, named.rejected_by) == (
                plain.value, plain.verdict, plain.rejected_by), (
                f"{name!r} in the title moved {case['title'][:48]!r}")


# --------------------------------------------- a search that is not in the US
#
# The shipped geography is one American's, and two of its checks are American
# knowledge rather than configuration: the `non_us` list, and the fallback that
# lets "Boise, Idaho" through on the strength of a state name. Both used to run
# whatever the user's own geography said, so a search run from London refused
# London for free, and called its own continent "outside the US".


def _config_for(city: str, tmp_path) -> search.SearchConfig:
    (tmp_path / "search.yaml").write_text(search.starter(city))
    search._load_cached.cache_clear()
    return search.load(tmp_path)


def somewhere(location: str) -> RawPosting:
    return RawPosting(employer="A Firm", title="Research Analyst", url="", source="t",
                      location=location, description="")


def test_a_london_search_scores_london_rather_than_refusing_it(tmp_path):
    config = _config_for("London", tmp_path)
    got = score(somewhere("London, United Kingdom"), config=config)

    assert got.rejected_by is None
    assert "London +25" in "; ".join(got.reasons)


def test_a_london_search_does_not_refuse_the_rest_of_its_own_country(tmp_path):
    """The state-name fallback called every foreign "City, Region" unrecognised."""
    config = _config_for("London", tmp_path)
    got = score(somewhere("Manchester, England"), config=config)

    assert got.rejected_by is None, got.reasons
    assert config.assume_us is False


def test_a_new_york_search_still_refuses_what_it_always_refused(tmp_path):
    config = _config_for("New York, NY", tmp_path)

    assert score(somewhere("London, United Kingdom"), config=config).rejected_by == "geography"
    assert score(somewhere("Kyiv, Ukraine"), config=config).rejected_by == "geography"
    assert score(somewhere("Boise, Idaho"), config=config).rejected_by is None


def test_the_shipped_defaults_are_still_a_us_search():
    """The frozen corpus above depends on this, and so does the reject wording."""
    assert SHIPPED.country == "us" and SHIPPED.assume_us
    assert "outside the US" in score(somewhere("London, England"),
                                     config=SHIPPED).reasons[0]


@pytest.mark.parametrize("city,location", [
    ("London", "London, United Kingdom"),            # one word
    ("New York, NY", "New York, NY"),                # two words and a state
    ("San Francisco", "San Francisco, CA"),          # two words, no state to fall back on
    ("Los Angeles", "Los Angeles, California"),      # …and a spelt-out state
    ("St. Louis, MO", "St.  Louis, MO"),             # punctuation, and a doubled space
])
def test_the_city_the_wizard_was_given_is_the_one_that_scores(city, location, tmp_path):
    """The whole point of writing a search.yaml: the answer reaches the gate.

    A label is not a match. `_pattern_for` used to escape the city and only
    then substitute `\\s+` for the space — but `re.escape` escapes a space too,
    so "New York" came out as a literal backslash followed by `s+` and matched
    nothing. The block was there, correctly labelled, scoring zero, and the
    user saw the consolation prizes underneath it instead.
    """
    config = _config_for(city, tmp_path)
    got = score(somewhere(location), config=config)

    assert got.rejected_by is None
    assert any(reason.endswith("+25") for reason in got.reasons), got.reasons


def test_a_starter_is_configuration_the_loader_accepts(tmp_path):
    for city in ("London", "New York, NY", "St. Louis, MO", "", "Zürich"):
        (tmp_path / "search.yaml").write_text(search.starter(city, "research"))
        search._load_cached.cache_clear()
        config = search.load(tmp_path)                       # compiles without raising
        assert config.thresholds == {"pursue": 70, "maybe": 45}   # untouched blocks


def test_the_threshold_the_gate_uses_is_the_profiles(tmp_path):
    """`apply search` prints this function's answer, not the config's own."""
    config = search.load(tmp_path)
    from apply.score import thresholds_in_force

    assert thresholds_in_force(config, {}) == {"pursue": 70, "maybe": 45}
    assert thresholds_in_force(config, {"thresholds": {"pursue": 40}}) == {
        "pursue": 40, "maybe": 45}
