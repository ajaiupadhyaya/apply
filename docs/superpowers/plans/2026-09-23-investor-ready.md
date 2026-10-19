# Investor-ready APPLY Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make APPLY a repository a stranger can clone, configure and run on macOS or Linux, and an investor can read and believe.

**Architecture:** Five independent work-streams on one branch. A fictional persona and an `apply setup` wizard replace the author's tracked profile as the scaffold. The relevance gate's vocabulary (cities, role patterns, timing, thresholds) moves from Python literals into a packaged YAML with per-user overrides, pinned first by a characterisation test so no score changes. The scheduler and secret lookup grow a platform layer so Linux reaches an unattended run. A fresh-clone smoke test in CI proves the quick start. The README leads with numbers a reader can reproduce.

**Tech Stack:** Python 3.11+, uv, Typer, FastAPI, SQLite, Jinja2 → LaTeX, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-23-investor-ready-design.md`

## Global Constraints

- Branch: `investor-ready`, already created from `origin/publish-ready`. Every task commits to it.
- `uv` for everything: `uv run apply ...`, `uv run pytest`, `uv add`. Never bare pip.
- **No new runtime dependencies.** `keyring` is used only via `importlib.util.find_spec` if the user already has it.
- The suite must pass on Python 3.11 and 3.13: `uv run pytest -q` and `uv run --python 3.11 --isolated pytest -q`.
- Lint must pass: `uvx ruff check --select F src tests`.
- Tests never call the Anthropic API. `tests/conftest.py` strips the key, blocks the Keychain lookup and trips on `llm.call`. Use the `fake_claude` fixture.
- Tests run against `tests/fixtures/profile.yaml`, never the live `data/profile.yaml`. Anything date-dependent pins its date.
- Never weaken `src/apply/outbound.py`, the human gates in `db.transition`, or `generate.lint`. `tests/test_acceptance.py` may be added to, never loosened.
- This repository is public: no personal data, no real employer strategy, no credentials in any committed file. Example files use invented values.
- Commit messages: sentence-case subject, body explaining *why*, ending with the trailer `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`. Never `git push --force`.
- Author's own `data/profile.yaml`, `data/profile.private.yaml`, `data/employers.yaml`, `data/apply.db`, `out/` stay untracked and unmodified on disk.

---

### Task 1: The persona and the setup wizard

**Files:**
- Create: `data/profile.example.yaml`
- Create: `src/apply/setup.py`
- Create: `tests/test_setup.py`
- Modify: `src/apply/cli.py` (add `setup` command; `init` scaffolds from the example)
- Modify: `.gitignore` (stop tracking `data/profile.yaml`)

**Interfaces:**
- Consumes: `apply.profile.data_dir() -> Path`, `apply.profile.Profile.load()`, `apply.generate.repo_root() -> Path`.
- Produces:
  - `apply.setup.EXAMPLE_PROFILE: Path` — the packaged persona file.
  - `apply.setup.Answers` — dataclass with fields `name: str`, `email: str`, `school: str`, `degree: str`, `grad_expected: str` (YYYY-MM), `city: str`, `work: str`, `authorized: bool`, `sponsorship: bool`, `links: dict[str, str]`.
  - `apply.setup.profile_from(answers: Answers) -> dict` — the profile mapping, persona-shaped.
  - `apply.setup.write_profile(data: dict, path: Path, *, force: bool = False) -> Path` — raises `FileExistsError` when the file exists and `force` is False.
  - `apply.setup.copy_examples(data: Path) -> list[Path]` — copies `*.example.yaml` to their live names when missing; returns what it created.
  - `apply.setup.ask(prompt_fn) -> Answers` — `prompt_fn(question: str, default: str) -> str`, so tests drive it without a terminal.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_setup.py
"""The front door: a stranger's first ten minutes."""

from __future__ import annotations

import pytest
import yaml

from apply import setup
from apply.profile import Profile


def test_the_persona_is_a_complete_profile():
    data = yaml.safe_load(setup.EXAMPLE_PROFILE.read_text())
    profile = Profile(data)
    assert profile.unresolved() == []          # nothing left as ASK
    assert data["education"][0]["grad_expected"]
    assert data["projects"] and data["experience"]
    assert "writing" in data


def test_the_persona_is_nobody_real():
    text = setup.EXAMPLE_PROFILE.read_text().lower()
    for fragment in ("upadhyaya", "vcu", "virginia commonwealth", "ohcamel"):
        assert fragment not in text


def test_answers_become_a_profile():
    answers = setup.Answers(
        name="Rae Mercer", email="rae@example.com", school="Example University",
        degree="BSc Economics", grad_expected="2027-06", city="London",
        work="research and analysis", authorized=True, sponsorship=False,
        links={"github": "https://github.com/example"})
    data = setup.profile_from(answers)
    assert data["identity"]["name"] == "Rae Mercer"
    assert data["education"][0]["grad_expected"] == "2027-06"
    assert data["authorization"]["requires_sponsorship_now"] is False
    Profile(data)                                   # constructs without error


def test_writing_refuses_to_overwrite(tmp_path):
    target = tmp_path / "profile.yaml"
    setup.write_profile({"identity": {"name": "A"}}, target)
    with pytest.raises(FileExistsError):
        setup.write_profile({"identity": {"name": "B"}}, target)
    setup.write_profile({"identity": {"name": "B"}}, target, force=True)
    assert "B" in target.read_text()


def test_examples_are_copied_only_when_missing(tmp_path):
    (tmp_path / "profile.private.example.yaml").write_text("a: 1\n")
    (tmp_path / "employers.example.yaml").write_text("employers: []\n")
    (tmp_path / "employers.yaml").write_text("employers: [{name: Mine}]\n")

    created = setup.copy_examples(tmp_path)

    assert (tmp_path / "profile.private.yaml").exists()
    assert [p.name for p in created] == ["profile.private.yaml"]
    assert "Mine" in (tmp_path / "employers.yaml").read_text()   # untouched


def test_the_wizard_asks_and_returns_answers():
    asked = []

    def prompt(question, default=""):
        asked.append(question)
        return {"name": "Rae Mercer", "email": "rae@example.com"}.get(
            _key(question), default)

    def _key(question):
        return "name" if "name" in question.lower() else (
            "email" if "email" in question.lower() else "")

    answers = setup.ask(prompt)
    assert answers.name == "Rae Mercer" and answers.email == "rae@example.com"
    assert len(asked) >= 8
```

- [ ] **Step 2: Run them and watch them fail**

Run: `uv run pytest tests/test_setup.py -q`
Expected: collection error, `No module named 'apply.setup'`.

- [ ] **Step 3: Write the persona**

Create `data/profile.example.yaml` as a complete, obviously-invented profile with the same shape as the current `data/profile.yaml` (read that file for the shape; copy the comment style, not the content). Use:

- identity: Rae Mercer, `rae.mercer@example.com`, London, links to `example.com`
- education: Example University, BSc Economics, `grad_expected: 2027-06`, one prior institution
- availability: `full_time: "from July 2027, after graduating"`, `internship: "summer 2027"`
- authorization: authorised in the UK, no sponsorship needed, `felony: false`, `veteran: false`
- experience: one role — research assistant in a university economics department — with three bullets and a `detail` paragraph
- projects: two — a rents-and-transit data study, and a small options-pricing library — each with `one_line`, `three_line`, `technical`, `resume_line`, `stack`, `tracks`
- skills, essays: `null`
- writing: the same brief structure as the live profile (voice, letter length/structure/proof asset per track, `answers.why_role`, an avoid list)

Every string must be plainly fictional. No real employer names.

- [ ] **Step 4: Write `src/apply/setup.py`**

```python
"""The first ten minutes: a profile that is yours, not its author's.

`apply init` used to scaffold from the author's own profile, which meant a
stranger's first act was deleting a biography. The scaffold is now a persona —
a complete fictional person, so the pipeline runs end to end on a fresh clone —
and `apply setup` turns a dozen answers into a profile of your own.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .generate import repo_root

EXAMPLE_PROFILE = repo_root() / "data" / "profile.example.yaml"

#: (attribute, question, default). The order the wizard asks in.
QUESTIONS = [
    ("name", "Your full name", ""),
    ("email", "Email for applications", ""),
    ("school", "School or university", ""),
    ("degree", "Degree, e.g. BS Finance", ""),
    ("grad_expected", "Graduation, YYYY-MM", ""),
    ("city", "Where you want to work", ""),
    ("work", "The work you want, in a few words", "research and analysis"),
]


@dataclass(slots=True)
class Answers:
    name: str = ""
    email: str = ""
    school: str = ""
    degree: str = ""
    grad_expected: str = ""
    city: str = ""
    work: str = ""
    authorized: bool = True
    sponsorship: bool = False
    links: dict[str, str] = field(default_factory=dict)


def persona() -> dict:
    return yaml.safe_load(EXAMPLE_PROFILE.read_text())


def profile_from(answers: Answers) -> dict:
    """The persona with the answers written over it.

    Everything the wizard does not ask — the writing brief, the shape of the
    projects block — is inherited from the persona, and everything it does ask
    replaces the persona's value outright. What is left over is marked ASK, so
    `apply doctor` lists it rather than a letter inventing it.
    """
    data = persona()
    data["identity"] = {
        **data.get("identity", {}),
        "name": answers.name,
        "email": answers.email,
        "location": answers.city,
        "links": answers.links or {},
    }
    education = data.get("education") or [{}]
    education[0] = {**education[0], "institution": answers.school,
                    "degree": answers.degree,
                    "grad_expected": answers.grad_expected, "current": True}
    data["education"] = education[:1]
    data["authorization"] = {
        "us_work_authorized": answers.authorized,
        "requires_sponsorship_now": answers.sponsorship,
        "requires_sponsorship_future": answers.sponsorship,
        "felony": False,
        "veteran": False,
    }
    data["experience"] = [{**(data.get("experience") or [{}])[0], "org": "ASK",
                           "title": "ASK", "start": "ASK"}]
    data["projects"] = []
    data["skills"] = data.get("skills") or {}
    data["essays"] = None
    data.setdefault("availability", {"full_time": "ASK", "internship": "ASK"})
    data["_note"] = (f"Scaffolded by `apply setup`. Fill in every ASK, add your "
                     f"projects, and check the writing brief. Target: {answers.work}.")
    return data


def write_profile(data: dict, path: Path, *, force: bool = False) -> Path:
    if path.exists() and not force:
        raise FileExistsError(f"{path} exists; pass --force to replace it")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    return path


def copy_examples(data: Path) -> list[Path]:
    """Copy each `*.example.yaml` to its live name, when that name is free."""
    created = []
    for example in sorted(data.glob("*.example.yaml")):
        live = data / example.name.replace(".example", "")
        if not live.exists():
            shutil.copyfile(example, live)
            created.append(live)
    return created


def ask(prompt_fn) -> Answers:
    answers = Answers()
    for attribute, question, default in QUESTIONS:
        setattr(answers, attribute, prompt_fn(question, default).strip() or default)
    answers.authorized = _yes(prompt_fn("Authorised to work there without sponsorship? [Y/n]", "y"))
    answers.sponsorship = not answers.authorized
    github = prompt_fn("GitHub URL (blank to skip)", "").strip()
    if github:
        answers.links = {"github": github}
    return answers


def _yes(value: str) -> bool:
    return not value.strip().lower().startswith("n")
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_setup.py -q`
Expected: PASS. Fix the persona file until `test_the_persona_is_a_complete_profile` passes — `Profile.unresolved()` returns the list of ASK values, so the persona must have none.

- [ ] **Step 6: Wire the CLI**

In `src/apply/cli.py`, add a `setup` command placed immediately before `init`, and change `init`'s scaffold source.

```python
@app.command()
def setup(
    persona: bool = typer.Option(False, "--persona", help="Write the example persona, unchanged."),
    force: bool = typer.Option(False, "--force", help="Replace an existing profile."),
    non_interactive: bool = typer.Option(False, "--non-interactive", help="Persona, no questions."),
) -> None:
    """Make this checkout yours: write a profile, then check the toolchain."""
    from . import setup as setup_mod

    target = data_dir() / "profile.yaml"
    if persona or non_interactive:
        data = setup_mod.persona()
    else:
        console.print("[dim]A dozen questions. Everything is editable afterwards in "
                      "data/profile.yaml.[/]\n")
        data = setup_mod.profile_from(setup_mod.ask(
            lambda question, default: typer.prompt(question, default=default)))
    try:
        setup_mod.write_profile(data, target, force=force)
    except FileExistsError:
        _fail(f"{target} already exists. Pass --force to replace it.")
    console.print(f"[green]✓[/] wrote [bold]{target}[/]")
    for created in setup_mod.copy_examples(data_dir()):
        console.print(f"[green]✓[/] created [bold]{created.name}[/] from its example")
    init()
```

In `init`, replace the scaffold template path with the example profile:

```python
        template = setup_mod.EXAMPLE_PROFILE
```

(add `from . import setup as setup_mod` inside `init`, matching how `init` already imports locally).

- [ ] **Step 7: Untrack the author's profile**

```bash
git rm --cached data/profile.yaml
printf 'data/profile.yaml\n' >> .gitignore
```

Check `.gitignore` does not already list it, and that `data/profile.example.yaml` is *not* ignored by any pattern: `git check-ignore -v data/profile.example.yaml` must print nothing.

- [ ] **Step 8: Prove the fresh-clone path by hand**

```bash
APPLY_DATA_DIR=$(mktemp -d) uv run apply setup --non-interactive
```

Expected: writes a profile, copies the examples, and `doctor` reports no ASK values. The author's own `data/profile.yaml` must still be on disk, unchanged: `git status --short data/` shows only the deletion of the tracked copy.

- [ ] **Step 9: Full suite and lint**

Run: `uv run pytest -q && uv run --python 3.11 --isolated pytest -q && uvx ruff check --select F src tests`
Expected: all green.

- [ ] **Step 10: Commit**

```bash
git add data/profile.example.yaml src/apply/setup.py tests/test_setup.py src/apply/cli.py .gitignore
git commit -m "A persona to start from, and a wizard to replace it

$(printf 'apply init scaffolded the author, so a stranger began by deleting a\nbiography. The scaffold is now a fictional persona, complete enough to\nrun the pipeline end to end, and apply setup turns a dozen answers into\na profile. data/profile.yaml is no longer tracked.\n')

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: The gate becomes configuration

**Files:**
- Create: `src/apply/search.defaults.yaml`
- Create: `src/apply/search.py`
- Create: `tests/test_search_config.py`
- Create: `tests/fixtures/score_corpus.json` (characterisation fixture, generated in Step 1)
- Modify: `src/apply/score.py` (read the vocabulary from config; keep the algorithm)
- Modify: `src/apply/cli.py` (add `search` command)
- Modify: `pyproject.toml` (ship the YAML inside the wheel)

**Interfaces:**
- Consumes: `apply.profile.data_dir()`, `apply.score.score(posting, preferences, standing)`.
- Produces:
  - `apply.search.SearchConfig` — frozen dataclass with `rejects: dict[str, re.Pattern]`, `role_fit: list[tuple[str, int]]`, `timing: list[tuple[str, int]]`, `title_timing: list[tuple[str, int]]`, `class_scoped: dict[str, re.Pattern]`, `geography: dict[str, tuple[re.Pattern, int]]`, `thresholds: dict[str, int]`, `sources: dict[str, str]` (block name → "defaults" or the override path).
  - `apply.search.load(data: Path | None = None) -> SearchConfig` — defaults deep-merged with `data/search.yaml` when present; cached per path.
  - `apply.score.score(posting, preferences=None, standing=None, config=None)` — `config` defaults to `search.load()`.

- [x] **Steps 1-3 are already done on this branch.** `tools/freeze_scores.py`
      wrote `tests/fixtures/score_corpus.json` (826 postings, titles and
      locations only — job descriptions belong to the employers who wrote them
      and this repo is public) plus a gitignored
      `tests/fixtures/score_corpus.local.json` carrying 150 real bodies for the
      body-dependent rules. `tests/test_search_config.py` asserts both.

      Before you change anything, run `uv run pytest tests/test_search_config.py -q`
      and confirm 4 passed. That test is the gate on this refactor: when it
      fails, your YAML transcription is wrong. **Never edit the fixture.**

- [ ] **Step 4: Write `src/apply/search.defaults.yaml`**

Transcribe — do not rewrite — every pattern currently in `src/apply/score.py`. Read the file first. The shape:

```yaml
# The gate's vocabulary. Copy any block into data/search.yaml to override it;
# what you leave out keeps the value here. `apply search` prints what is in force.
thresholds: {pursue: 70, maybe: 45}

rejects:
  seniority: ["(?<!rising\\s)senior(?!\\s+year)", "sr\\.?", "vice\\s+president", ...]
  off_function: ["sales(?!\\s*(?:and|&)\\s*trading)", ...]
  too_technical: ["software\\s+engineer\\w*", ...]
  graduate_program: ["\\bph\\.?\\s?d\\b", ...]

class_scoped:
  freshman: ["freshman", "first[\\s-]?year\\s+(student|intern)"]
  sophomore: ["sophomore"]
  junior: ["rising\\s+junior(?!\\s+or)", "junior\\s+year"]
  senior: ["rising\\s+senior(?!\\s+or)"]

geography:
  # name: {weight, patterns}. The first match in this order wins.
  primary: {weight: 25, label: "New York", patterns: ["new\\s+york", "\\bnyc\\b", ...]}
  home:    {weight: 15, label: "local", patterns: ["richmond", "charlottesville", ...]}
  remote:  {weight: 10, label: "remote", patterns: ["remote", "work\\s+from\\s+home", ...]}
  hub:     {weight: 6,  label: "US finance hub", patterns: ["boston", "chicago", ...]}
non_us: ["london", "hong\\s+kong", ...]

role_fit:
  - ["quantitative[\\s\\w]{0,18}(research\\w*|analyst|trader|trading)", 25]
  # … every pair from ROLE_FIT, in order
timing:
  - ["pre[\\s-]?doctoral|predoc", 20]
  # … every pair from TIMING
title_timing:
  - ["\\b20(26|27)\\b", 14]
  - ["\\bclass\\s+of\\b", 14]
```

- [ ] **Step 5: Write `src/apply/search.py`**

```python
"""What the gate is looking for, as data rather than as literals.

The algorithm in score.py is general: reject on these patterns, weight a title
against these, add for a place. The vocabulary was specific — one person's
city, field and graduating year, written into the source. It lives here now:
defaults shipped with the package, overridden per block by data/search.yaml.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

DEFAULTS = Path(__file__).resolve().parent / "search.defaults.yaml"


def _any(patterns: list[str]) -> re.Pattern:
    """Whole-token alternation, the form score.py has always used."""
    return re.compile("|".join(rf"(?<![A-Za-z0-9]){p}(?![A-Za-z0-9])" for p in patterns), re.I)


@dataclass(frozen=True, slots=True)
class SearchConfig:
    rejects: dict[str, re.Pattern]
    class_scoped: dict[str, re.Pattern]
    geography: tuple[tuple[str, str, int, re.Pattern], ...]   # key, label, weight, pattern
    non_us: re.Pattern
    role_fit: tuple[tuple[str, int], ...]
    timing: tuple[tuple[str, int], ...]
    title_timing: tuple[tuple[str, int], ...]
    thresholds: dict[str, int]
    sources: dict[str, str]


def _merge(base: dict, override: dict) -> tuple[dict, dict[str, str]]:
    merged = dict(base)
    sources = {key: "defaults" for key in base}
    for key, value in (override or {}).items():
        merged[key] = value
        sources[key] = "data/search.yaml"
    return merged, sources


def build(raw: dict, sources: dict[str, str]) -> SearchConfig:
    geography = tuple(
        (key, block.get("label", key), int(block["weight"]), _any(block["patterns"]))
        for key, block in (raw.get("geography") or {}).items())
    return SearchConfig(
        rejects={name: _any(patterns) for name, patterns in (raw.get("rejects") or {}).items()},
        class_scoped={year: _any(patterns)
                      for year, patterns in (raw.get("class_scoped") or {}).items()},
        geography=geography,
        non_us=_any(raw.get("non_us") or []),
        role_fit=tuple((p, int(w)) for p, w in raw.get("role_fit") or []),
        timing=tuple((p, int(w)) for p, w in raw.get("timing") or []),
        title_timing=tuple((p, int(w)) for p, w in raw.get("title_timing") or []),
        thresholds={**{"pursue": 70, "maybe": 45}, **(raw.get("thresholds") or {})},
        sources=sources,
    )


@lru_cache(maxsize=8)
def _load_cached(path: str | None) -> SearchConfig:
    raw = yaml.safe_load(DEFAULTS.read_text()) or {}
    override = {}
    if path and Path(path).exists():
        override = yaml.safe_load(Path(path).read_text()) or {}
    merged, sources = _merge(raw, override)
    return build(merged, sources)


def load(data: Path | None = None) -> SearchConfig:
    """The configuration in force. `data` defaults to the profile's data dir."""
    if data is None:
        from .profile import data_dir

        data = data_dir()
    return _load_cached(str(Path(data) / "search.yaml"))
```

- [ ] **Step 6: Rewire `score.py` to the config**

Keep every function name and the whole algorithm. Replace the module-level constants with lookups on a `SearchConfig` passed into `score()`:

```python
def score(posting, preferences=None, standing=None, config=None):
    from . import search as search_mod

    config = config or search_mod.load()
    ...
    thresholds = {**config.thresholds, **(preferences.get("thresholds") or {})}
    ...
    for name, pattern in config.rejects.items():
        hit = pattern.search(title)
        if hit:
            return reject(f"{_REJECT_REASON[name]}: {hit.group(0)!r}", _REJECT_LABEL[name])
```

Keep `_REJECT_REASON` / `_REJECT_LABEL` as small dicts in `score.py` so the existing rejection strings and `rejected_by` labels (`"seniority"`, `"function"`, `"technical"`, `"degree"`) are unchanged — `tests/test_score.py`, `tests/test_boards.py` and `tests/test_rescore.py` assert on them.

Geography becomes a loop over `config.geography`, keeping the "first match wins" order and appending the same reason strings (`"New York +25"` becomes `f"{label} +{weight}"`; update the two tests that assert the exact string, and only those).

`GRADUATE_PROGRAM`, `YEARS`, `ADVANCED_DEGREE`, `GRAD_WINDOW`, `graduation_window()` and the hydration cap stay in `score.py` as they are: they are algorithm, not vocabulary.

- [ ] **Step 7: Run the characterisation test**

Run: `uv run pytest tests/test_search_config.py -q`
Expected: PASS, unchanged. If any verdict moved, the transcription is wrong — fix the YAML, never the fixture.

- [ ] **Step 8: Add the override tests**

```python
def test_an_override_replaces_one_block_and_keeps_the_rest(tmp_path):
    (tmp_path / "search.yaml").write_text(
        "geography:\n"
        "  primary: {weight: 30, label: Berlin, patterns: [berlin]}\n")
    config = search.load(tmp_path)

    assert [g[1] for g in config.geography] == ["Berlin"]
    assert config.thresholds == {"pursue": 70, "maybe": 45}      # untouched
    assert config.sources["geography"] == "data/search.yaml"
    assert config.sources["role_fit"] == "defaults"


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
    with pytest.raises(KeyError):
        search.load(tmp_path)
```

Note: `search.load` is cached per path, so each test needs its own `tmp_path` — they do.

- [ ] **Step 9: Add `apply search`**

```python
@app.command()
def search() -> None:
    """The relevance gate's configuration, and where each block came from."""
    from . import search as search_mod

    config = search_mod.load()
    table = Table(box=None, header_style="dim", padding=(0, 2))
    for column in ("block", "entries", "from"):
        table.add_column(column, justify="right" if column == "entries" else "left")
    for name, size in (("thresholds", len(config.thresholds)),
                       ("rejects", sum(1 for _ in config.rejects)),
                       ("geography", len(config.geography)),
                       ("role_fit", len(config.role_fit)),
                       ("timing", len(config.timing)),
                       ("class_scoped", len(config.class_scoped))):
        table.add_row(name, str(size), config.sources.get(name, "defaults"))
    console.print(table)
    console.print(f"\n[dim]thresholds: pursue ≥ {config.thresholds['pursue']}, "
                  f"maybe ≥ {config.thresholds['maybe']}. Override any block in "
                  f"data/search.yaml.[/]")
```

- [ ] **Step 10: Ship the YAML in the wheel**

In `pyproject.toml`, under `[tool.hatch.build.targets.wheel]`, add:

```toml
[tool.hatch.build.targets.wheel.force-include]
"src/apply/search.defaults.yaml" = "apply/search.defaults.yaml"
```

- [ ] **Step 11: Full suite, both versions, lint**

Run: `uv run pytest -q && uv run --python 3.11 --isolated pytest -q && uvx ruff check --select F src tests`
Expected: all green, including the characterisation test.

- [ ] **Step 12: Commit**

```bash
git add src/apply/search.py src/apply/search.defaults.yaml src/apply/score.py src/apply/cli.py tests/test_search_config.py pyproject.toml
git commit -m "The gate's vocabulary moves to YAML; its verdicts do not move

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Linux reaches the morning run

**Files:**
- Create: `src/apply/secrets.py`
- Create: `tests/test_secrets.py`
- Create: `tests/test_schedule.py`
- Modify: `src/apply/schedule.py` (platform backends)
- Modify: `src/apply/llm.py`, `src/apply/run.py`, `src/apply/cli.py` (use `secrets.lookup`)
- Modify: `src/apply/notify.py` (`notify-send` on Linux)
- Modify: `.github/workflows/tests.yml` (os matrix)

**Interfaces:**
- Produces:
  - `apply.secrets.lookup(name: str) -> str | None` — environment, then macOS Keychain, then `keyring` if installed.
  - `apply.secrets.INSTRUCTIONS: dict[str, str]` — per-platform text telling the user how to store a secret.
  - `apply.schedule.backend(platform: str | None = None)` — returns `LaunchdBackend()`, `SystemdBackend()` or `CronBackend()`, each with `render(schedule) -> str`, `install(schedule) -> Path | str`, `remove() -> bool`, `status() -> dict`.
  - `apply.schedule.Schedule` keeps its fields (`hour`, `minute`, `project`, `command`).

- [ ] **Step 1: Write the failing secret tests**

```python
# tests/test_secrets.py
"""One order for every secret, on every platform."""

from __future__ import annotations

from apply import secrets


def test_the_environment_wins(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    monkeypatch.setattr(secrets, "_from_keychain", lambda name: "from-keychain")
    assert secrets.lookup("ANTHROPIC_API_KEY") == "from-env"


def test_the_keychain_is_next(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(secrets, "_from_keychain", lambda name: "from-keychain")
    monkeypatch.setattr(secrets, "_from_keyring", lambda name: "from-keyring")
    assert secrets.lookup("ANTHROPIC_API_KEY") == "from-keychain"


def test_keyring_is_the_linux_fallback(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(secrets, "_from_keychain", lambda name: None)
    monkeypatch.setattr(secrets, "_from_keyring", lambda name: "from-keyring")
    assert secrets.lookup("ANTHROPIC_API_KEY") == "from-keyring"


def test_nothing_found_is_none(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(secrets, "_from_keychain", lambda name: None)
    monkeypatch.setattr(secrets, "_from_keyring", lambda name: None)
    assert secrets.lookup("ANTHROPIC_API_KEY") is None


def test_an_empty_value_is_not_a_secret(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
    monkeypatch.setattr(secrets, "_from_keychain", lambda name: None)
    monkeypatch.setattr(secrets, "_from_keyring", lambda name: None)
    assert secrets.lookup("ANTHROPIC_API_KEY") is None


def test_instructions_exist_for_both_platforms():
    assert "security add-generic-password" in secrets.INSTRUCTIONS["darwin"]
    assert "keyring" in secrets.INSTRUCTIONS["linux"] or "export" in secrets.INSTRUCTIONS["linux"]
```

- [ ] **Step 2: Run them, watch them fail**

Run: `uv run pytest tests/test_secrets.py -q`
Expected: `No module named 'apply.secrets'`.

- [ ] **Step 3: Write `src/apply/secrets.py`**

```python
"""Where a secret comes from, in one place and one order.

The order is: the environment, then the macOS Keychain, then a Secret Service
keyring if the user happens to have one. A scheduled run is why the Keychain
lookup exists at all — launchd and cron both start a shell that never reads a
profile, so an exported variable is simply absent at 06:30.

Nothing here writes a secret anywhere, and no value is ever logged.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys

INSTRUCTIONS = {
    "darwin": ('security add-generic-password -U -a "$USER" -s {name} -w'),
    "linux": ("keyring set apply {name}        # if python-keyring is installed\n"
              "  or: export {name}=...        # in the shell that runs apply"),
    "other": "export {name}=...",
}


def platform_key() -> str:
    if sys.platform == "darwin":
        return "darwin"
    return "linux" if sys.platform.startswith("linux") else "other"


def how_to_store(name: str) -> str:
    return INSTRUCTIONS[platform_key()].format(name=name)


def _from_keychain(name: str) -> str | None:
    if sys.platform != "darwin" or not shutil.which("security"):
        return None
    result = subprocess.run(
        ["security", "find-generic-password", "-a", os.environ.get("USER", ""),
         "-s", name, "-w"],
        capture_output=True, text=True,
    )
    return (result.stdout.strip() or None) if result.returncode == 0 else None


def _from_keyring(name: str) -> str | None:
    from importlib.util import find_spec

    if find_spec("keyring") is None:            # never a dependency of this project
        return None
    try:
        import keyring

        return keyring.get_password("apply", name) or None
    except Exception:                            # noqa: BLE001 — a locked or absent backend
        return None


def lookup(name: str) -> str | None:
    """The secret, or None. Environment first, then the platform's store."""
    for source in (lambda n: os.environ.get(n), _from_keychain, _from_keyring):
        value = source(name)
        if value and value.strip():
            return value.strip()
    return None
```

- [ ] **Step 4: Run the secret tests**

Run: `uv run pytest tests/test_secrets.py -q`
Expected: PASS.

- [ ] **Step 5: Route the existing callers through it**

- `src/apply/llm.py`: keep `_keychain_key` as a thin alias so `tests/conftest.py` keeps working (it patches that name), but have `available()` and `_client()` call `secrets.lookup("ANTHROPIC_API_KEY")`. Update `NO_CREDENTIAL` to use `secrets.how_to_store("ANTHROPIC_API_KEY")`.
- `src/apply/run.py:158-162`: replace the env-then-keychain pair with `secrets.lookup("APPLY_IMAP_PASSWORD")`.
- `src/apply/cli.py:1148-1151`: the same.

Check `tests/conftest.py` still blocks every path: it patches `llm._keychain_key`; add a patch of `apply.secrets.lookup` returning `None` in the same autouse fixture so no test can read a real key.

- [ ] **Step 6: Write the scheduler tests**

```python
# tests/test_schedule.py
"""The morning run, on both platforms. No file outside tmp_path is touched."""

from __future__ import annotations

from pathlib import Path

import pytest

from apply import schedule as schedule_mod


@pytest.fixture
def plan(tmp_path):
    return schedule_mod.Schedule(hour=6, minute=30, project=tmp_path)


def test_launchd_renders_a_plist(plan):
    text = schedule_mod.backend("darwin").render(plan)
    assert "<key>StartCalendarInterval</key>" in text
    assert "apply run --notify" in text


def test_systemd_renders_a_timer_and_a_service(plan):
    rendered = schedule_mod.backend("linux").render(plan)
    assert "OnCalendar=*-*-* 06:30:00" in rendered
    assert "Type=oneshot" in rendered
    assert str(plan.project) in rendered


def test_cron_renders_one_line(plan):
    line = schedule_mod.CronBackend().render(plan)
    assert line.startswith("30 6 * * *")
    assert "apply run --notify" in line
    assert schedule_mod.CronBackend.MARKER in line


def test_installing_a_timer_writes_only_under_the_unit_dir(tmp_path, monkeypatch):
    units = tmp_path / "units"
    monkeypatch.setattr(schedule_mod.SystemdBackend, "unit_dir", lambda self: units)
    calls = []
    monkeypatch.setattr(schedule_mod, "_run", lambda *args: calls.append(args))

    schedule_mod.SystemdBackend().install(schedule_mod.Schedule(project=tmp_path))

    assert (units / "apply.service").exists() and (units / "apply.timer").exists()
    assert any("--user" in " ".join(call[0]) for call in calls)


def test_removing_a_cron_line_keeps_the_others(monkeypatch):
    existing = "0 9 * * * backup\n30 6 * * * cd /x && uv run apply run --notify  # apply\n"
    written = {}
    monkeypatch.setattr(schedule_mod.CronBackend, "_read", lambda self: existing)
    monkeypatch.setattr(schedule_mod.CronBackend, "_write",
                        lambda self, text: written.setdefault("text", text))

    assert schedule_mod.CronBackend().remove() is True
    assert "backup" in written["text"] and "apply run" not in written["text"]


def test_the_backend_follows_the_platform(monkeypatch):
    assert isinstance(schedule_mod.backend("darwin"), schedule_mod.LaunchdBackend)
    monkeypatch.setattr(schedule_mod.shutil, "which", lambda name: "/usr/bin/systemctl")
    assert isinstance(schedule_mod.backend("linux"), schedule_mod.SystemdBackend)
    monkeypatch.setattr(schedule_mod.shutil, "which", lambda name: None)
    assert isinstance(schedule_mod.backend("linux"), schedule_mod.CronBackend)
```

- [ ] **Step 7: Restructure `src/apply/schedule.py`**

Keep `Schedule`, `LABEL` (rename the constant's value to `"apply"` for the systemd unit name but keep the launchd label string as it is, so an existing installed agent is still found), and the existing launchd code, moved into `LaunchdBackend`. Add:

```python
SERVICE = """[Unit]
Description=apply: one unattended pass

[Service]
Type=oneshot
WorkingDirectory={project}
ExecStart=/bin/sh -lc '{command}'
"""

TIMER = """[Unit]
Description=apply: {at} every day

[Timer]
OnCalendar=*-*-* {at}:00
Persistent=true

[Install]
WantedBy=timers.target
"""
```

`SystemdBackend.unit_dir()` returns `Path.home() / ".config" / "systemd" / "user"`; `install` writes both units, then runs `systemctl --user daemon-reload`, `systemctl --user enable --now apply.timer` through a module-level `_run(argv)` helper so tests can intercept it. `Persistent=true` is the systemd equivalent of launchd catching up a missed run.

`CronBackend` keeps a `MARKER = "# apply"` comment on its line, reads with `crontab -l`, writes with `crontab -` through the same `_run` helper, and never touches a line without the marker.

`backend(platform=None)` picks: `darwin` → launchd; linux with `systemctl` on PATH → systemd; linux without → cron; anything else raises `RuntimeError("no scheduler for this platform; run `apply run` from your own cron")`.

`install/remove/status` at module level keep working by delegating to `backend()`, so `cli.py` needs no change beyond its help text.

- [ ] **Step 8: Linux notifications**

In `src/apply/notify.py`, `banner()` gains a Linux branch: when `sys.platform.startswith("linux")` and `shutil.which("notify-send")`, run `["notify-send", title, message]` and return whether it exited 0. Everything else still returns False.

- [ ] **Step 9: CI on both platforms**

In `.github/workflows/tests.yml`, replace `runs-on: ubuntu-latest` with `runs-on: ${{ matrix.os }}` and add to the matrix:

```yaml
        os: [ubuntu-latest, macos-latest]
        python: ["3.11", "3.13"]
```

- [ ] **Step 10: Suite, both versions, lint**

Run: `uv run pytest -q && uv run --python 3.11 --isolated pytest -q && uvx ruff check --select F src tests`
Expected: green. The scheduler tests must not write outside `tmp_path`: check with `git status --short` afterwards.

- [ ] **Step 11: Commit**

```bash
git add src/apply/secrets.py src/apply/schedule.py src/apply/notify.py src/apply/llm.py src/apply/run.py src/apply/cli.py tests/test_secrets.py tests/test_schedule.py .github/workflows/tests.yml
git commit -m "Linux gets the morning run, and secrets get one lookup order

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: The completeness audit

**Files:**
- Create: `tests/test_fresh_clone.py`
- Modify: `.github/workflows/tests.yml` (a smoke job)
- Modify: `src/apply/db.py` and/or `src/apply/cli.py` (resolve the unused `contact` table)
- Modify: `README.md` (command table completeness only; Task 5 owns the prose)

**Interfaces:**
- Consumes: everything Tasks 1–3 produce.
- Produces: nothing other tasks depend on.

- [ ] **Step 1: Write the fresh-clone test**

```python
# tests/test_fresh_clone.py
"""What a stranger gets: every command, on a data directory that starts empty.

This is the quick start as a test. It runs the real CLI through Typer's runner
against a temporary data directory, so it can never touch the author's files.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apply.cli import app


@pytest.fixture
def fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("APPLY_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("APPLY_OUT_DIR", str(tmp_path / "out"))
    (tmp_path / "data").mkdir()
    return CliRunner()


def run(runner, *args):
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, f"{args} exited {result.exit_code}\n{result.output}"
    return result.output


def test_the_quick_start_works_on_an_empty_directory(fresh):
    run(fresh, "setup", "--non-interactive")
    run(fresh, "seed")
    assert "pursue" in run(fresh, "status") or "draft" in run(fresh, "status")
    run(fresh, "digest")
    run(fresh, "targets")
    run(fresh, "search")
    run(fresh, "rescore", "--dry-run")
    run(fresh, "spend")


def test_every_command_in_help_is_documented_in_the_readme(fresh):
    from apply.generate import repo_root

    listed = {line.split()[0] for line in run(fresh, "--help").splitlines()
              if line.startswith("  ") and line.strip() and line.strip()[0].isalpha()}
    readme = (repo_root() / "README.md").read_text()
    missing = sorted(name for name in listed if f"apply {name}" not in readme)
    assert missing == [], f"commands with no line in the README: {missing}"


def test_the_dashboard_answers_on_a_fresh_profile(fresh):
    from fastapi.testclient import TestClient

    run(fresh, "setup", "--non-interactive")
    run(fresh, "seed")
    from apply.web.app import app as web

    response = TestClient(web).get("/")
    assert response.status_code == 200
```

- [ ] **Step 2: Run it and fix what it finds**

Run: `uv run pytest tests/test_fresh_clone.py -q`
Expected: failures that are real findings. Fix each in the command, not in the test, unless the test is wrong. Likely findings: `seed` writing outside the data dir, `status` failing on an empty pipeline, `--help` names missing from the README table.

- [ ] **Step 3: Resolve the unused `contact` table**

Run `grep -rn "contact" src/ | grep -v "^src/apply/db.py"`. If nothing writes to it, delete the table from `db.py`'s schema and from the migration list, and note the removal in the commit message. Do not add a feature to justify a table.

- [ ] **Step 4: Add the smoke job to CI**

```yaml
  smoke:
    runs-on: ${{ matrix.os }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest]
    steps:
      - uses: actions/checkout@v7
      - uses: astral-sh/setup-uv@v10.2.0
      - run: uv sync
      # The quick start, exactly as the README prints it, on a clone with no
      # profile of its own. No API key: nothing here calls a model.
      - run: |
          rm -f data/profile.yaml
          uv run apply setup --non-interactive
          uv run apply seed
          uv run apply status
          uv run apply digest
          uv run apply search
          uv run apply targets
```

- [ ] **Step 5: Suite, both versions, lint**

Run: `uv run pytest -q && uv run --python 3.11 --isolated pytest -q && uvx ruff check --select F src tests`

- [ ] **Step 6: Commit**

```bash
git add tests/test_fresh_clone.py .github/workflows/tests.yml src/apply/db.py src/apply/cli.py README.md
git commit -m "The quick start becomes a test, on both platforms

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: A README that shows its working

**Files:**
- Create: `tools/numbers.py`
- Modify: `README.md`
- Modify: `CLAUDE.md` (the public-repo rules gain the persona and `data/search.yaml`)

**Interfaces:**
- Consumes: `apply.search.load()`, `apply.discover.load_employers()`, the ledger in `apply.budget`.
- Produces: `tools/numbers.py` printing a markdown table, so the README's figures are reproducible rather than remembered.

- [ ] **Step 1: Write the numbers script**

```python
# tools/numbers.py
"""Every figure the README quotes, recomputed from this machine.

Run it before editing the README. The point is that a reader can run it too,
against their own pipeline, and get their own numbers.
"""

from __future__ import annotations

import sqlite3
from collections import Counter

from apply.discover import load_employers
from apply.profile import data_dir


def main() -> None:
    employers = load_employers()
    kinds = Counter(e.get("ats", "?") for e in employers)
    print(f"registry: {len(employers)} firms — "
          + ", ".join(f"{n} {k}" for k, n in kinds.most_common()))

    conn = sqlite3.connect(data_dir() / "apply.db")
    postings, pursue, maybe, rejected = conn.execute(
        "SELECT count(*), sum(score_verdict='pursue'), sum(score_verdict='maybe'),"
        " sum(score_verdict='reject') FROM posting").fetchone()
    print(f"filed: {postings} postings — {pursue} pursue, {maybe} maybe, "
          f"{rejected} screened out by later gate changes")

    spend, calls = conn.execute("SELECT sum(usd), count(*) FROM spend").fetchone()
    letters = conn.execute(
        "SELECT count(DISTINCT slug) FROM spend WHERE purpose LIKE 'write%'").fetchone()[0]
    if letters:
        print(f"model spend: ${spend:.2f} over {calls} calls for {letters} letters "
              f"(${spend / letters:.2f} a letter)")


if __name__ == "__main__":
    main()
```

Run: `uv run python tools/numbers.py` and keep the output — the README quotes it.

- [ ] **Step 2: Rewrite the README's opening**

Replace the first section (down to "What it will not do") with: the one-line claim, the pipeline diagram that is already there, and a short "What it has done so far" block carrying the real figures from Step 1, each labelled *one person's search, as of 2026-09-23*. Keep the existing tone: plain sentences, no marketing adjectives, no emoji.

State the honest limits in the same block: it was built for one search, the gate's defaults are tuned for that search, and retuning is a YAML file.

- [ ] **Step 3: Replace "Retuning it" with "Make it yours"**

Cover, in order: `apply setup`, the three data files and which are gitignored, `data/search.yaml` with a worked example (move the primary city to Berlin, add a role pattern), adding an employer with `apply resolve`, and where the alert-mail guides are.

- [ ] **Step 4: Update the quick start**

It must match what CI's smoke job runs: `git clone`, `uv sync`, TeX note, the key, `uv run apply setup`, `uv run apply seed`, `uv run apply serve`. Show the Linux and macOS key commands separately, from `secrets.how_to_store`.

- [ ] **Step 5: Update `CLAUDE.md`**

Add to the public-repo section: `data/profile.yaml` and `data/search.yaml` are gitignored; the persona in `data/profile.example.yaml` is fictional and must stay fictional.

- [ ] **Step 6: Check every command is in the README table**

Run: `uv run pytest tests/test_fresh_clone.py::test_every_command_in_help_is_documented_in_the_readme -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add README.md CLAUDE.md tools/numbers.py
git commit -m "README: the numbers, and how to make it yours

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Screenshots (main session, not a subagent)

**Files:**
- Create: `docs/img/pipeline.png`, `docs/img/posting.png`
- Modify: `README.md` (embed them)

- [ ] **Step 1:** With `APPLY_DATA_DIR` pointed at a temporary directory, run `apply setup --persona`, `apply seed`, and `apply serve --no-open --port 8788`.
- [ ] **Step 2:** Screenshot the pipeline page and one posting page through the browser pane at desktop width.
- [ ] **Step 3:** Confirm no real employer name and none of the author's details appear in either image.
- [ ] **Step 4:** Embed both in the README under the opening block, and commit.

---

## Self-review

**Spec coverage.** A → Task 1. B → Task 2. C → Task 3. D → Task 4. E → Tasks 5 and 6. The spec's `apply search` command is in Task 2 Step 9; its anonymised characterisation fixture is Task 2 Step 1; its "no new runtime dependencies" constraint is honoured by `secrets._from_keyring` using `find_spec`.

**Placeholders.** None: every code step carries its code, and the two steps that transcribe existing content (the persona, `search.defaults.yaml`) name the file to copy the shape from and the constraints on the values.

**Type consistency.** `SearchConfig.geography` is a tuple of `(key, label, weight, pattern)` in both the dataclass and `build()`; `score()` takes `config=None` everywhere; `secrets.lookup(name)` has one signature; `backend(platform=None)` returns the three classes the tests name. `Answers` fields match `profile_from`'s reads and the wizard's writes.
