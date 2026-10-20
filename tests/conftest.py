"""Test fixtures.

Every test runs against a temporary data directory and a temporary out/, so the
suite can never touch the owner's real apply.db, profile, or generated letters —
and, just as important, nothing the owner has written in data/ can change what
the suite reports. That is what `isolated_data_dir` below is for, and it is
autouse because the guarantee has to hold for the tests that never think to ask
for it.
"""

from __future__ import annotations

import os

# Before anything imports apply.cli, which builds its rich Console at import
# time and reads the environment exactly once. CI is not a terminal, but it sets
# CI=true, which rich reads as "colour is fine" — so a test that parses CLI
# output sees ANSI escapes on the runner and none on a laptop, and fails only
# there. A fixture cannot fix this: by then the Console exists.
os.environ["NO_COLOR"] = "1"
os.environ["TERM"] = "dumb"
os.environ["COLUMNS"] = "200"
os.environ.pop("FORCE_COLOR", None)

import shutil                                                        # noqa: E402
from pathlib import Path                                             # noqa: E402

import pytest                                                        # noqa: E402

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
#: The two example postings `apply seed` loads — invented firms, invented roles.
#: Shipped with the repo, not the tests.
EXAMPLES = REPO / "data" / "examples"


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """An empty data/ and out/ for every test, whatever the checkout holds.

    Only tests that asked for `workspace` used to get this. Everything else read
    the repository's own data/ — so `apply setup`, which the README's quick start
    tells a stranger to run, wrote a data/search.yaml that silently replaced the
    relevance gate's geography underneath the frozen scoring corpus. A cloner who
    lives anywhere but New York got twelve failures on a clean checkout, and the
    README said what is in data/ changes nothing.

    The directory starts empty, which is what a fresh clone has. A test that
    needs a profile in it asks for `workspace`; a test that needs a particular
    search configuration writes one and says so.
    """
    from apply import search

    data = tmp_path / "data"
    data.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setenv("APPLY_DATA_DIR", str(data))
    monkeypatch.setenv("APPLY_OUT_DIR", str(out))

    # A SearchConfig is cached per path, and that cache is meant to last one CLI
    # command. In a test run the process is the whole session, so a config built
    # from one test's search.yaml would answer another test's load() for any
    # path it happened to reuse. Clear it on both sides of every test.
    search._load_cached.cache_clear()
    yield data
    search._load_cached.cache_clear()


@pytest.fixture
def workspace(isolated_data_dir, tmp_path):
    """The isolated data dir, with the persona's profile written into it."""
    shutil.copy(FIXTURES / "profile.yaml", isolated_data_dir / "profile.yaml")
    return tmp_path


@pytest.fixture
def profile(workspace):
    from apply.profile import Profile

    return Profile.load()


@pytest.fixture
def conn(workspace):
    from apply import db

    db.init_db()
    connection = db.connect()
    yield connection
    connection.close()


@pytest.fixture
def quillon_jd() -> str:
    return (EXAMPLES / "quillon.txt").read_text(encoding="utf-8")


@pytest.fixture
def ashcombe_jd() -> str:
    return (EXAMPLES / "ashcombe.txt").read_text(encoding="utf-8")


def posting_from(text: str, **overrides):
    from apply.parse import parse

    parsed = parse(text)
    posting = parsed.to_posting()
    for key, value in overrides.items():
        setattr(posting, key, value)
    return posting


# ------------------------------------------------------ never call the API
#
# ~/.zshrc exports a real key, so a test run from a terminal would otherwise
# make real, billed requests. Every test runs with the credential stripped and a
# tripwire on the one function that talks to Anthropic. Tests that exercise the
# writer pass a FakeClaude explicitly.

@pytest.fixture(autouse=True)
def _no_real_api(monkeypatch, tmp_path):
    from apply import llm, secrets

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(llm, "_profile_dir", lambda: tmp_path / "no-anthropic-profile")
    monkeypatch.setattr(llm, "_keychain_key", lambda *a, **k: None)
    # Every credential now arrives through secrets.lookup, so that is the door
    # to bar: blocked here, plus both platform stores under it, so no test can
    # read a key out of a real Keychain. tests/test_secrets.py keeps a
    # reference to the genuine function, taken at import time.
    monkeypatch.setattr(secrets, "lookup", lambda name: None)
    monkeypatch.setattr(secrets, "_from_keychain", lambda name: None)
    monkeypatch.setattr(secrets, "_from_keyring", lambda name: None)
    monkeypatch.setattr(secrets, "store",
                        lambda *a, **k: pytest.fail("a test tried to store a real secret"))

    def tripwire(*_, **__):
        raise AssertionError("a test tried to call the real Anthropic API")

    monkeypatch.setattr(llm, "call", tripwire)
    monkeypatch.setattr(llm, "ping", tripwire)


# A draft that passes the lint, written from the fixture profile — the persona's
# facts and nobody else's. Every claim here is traceable to tests/fixtures/
# profile.yaml, which is what makes it a *clean* draft rather than merely a
# well-behaved one.
CLEAN = dict(
    paragraph_1=("I am applying for the Investment Intern role at Ashcombe Trust. "
                 "As an Economics student at Example University graduating in June "
                 "2027, I bring experience in research data and quantitative "
                 "analysis that suits the work of the Investment Committee."),
    paragraph_2=("My research experience comes from the Department of Economics, "
                 "where I assemble and document panel datasets for two faculty "
                 "housing studies. Reconciling sources that define the same "
                 "quarter differently is a central part of the work, and it is the "
                 "same care the Investment Committee requires of its data."),
    paragraph_3=("Two independent projects add quantitative depth. Rents and "
                 "Transit studies advertised rents along a new rail corridor, and "
                 "Vanilla is an options-pricing library that reports its "
                 "assumptions alongside each price."),
    paragraph_4=("Ashcombe Trust's Investment Committee holds a view across "
                 "managers and asset classes, and that breadth is what draws me to "
                 "the role. Careful, documented analysis is the contribution I "
                 "would make to it."),
    closing=("I am authorized to work in the United States and will not require "
             "sponsorship, now or in the future. Thank you for your time and "
             "consideration; I would welcome the opportunity to discuss my "
             "application."),
    proof_asset="The research assistant role",
    anchor_used="the Investment Committee",
    why_role_short=("The posting asks for careful work on the data the investment "
                    "team relies on, which is what I do now for the faculty I "
                    "support."),
    why_role_long=("The posting asks for careful work on the data the investment team "
                   "relies on for asset allocation, and for writing that goes to the "
                   "Investment Committee. I already reconcile series that three "
                   "public sources report on different bases, and I wrote the data "
                   "appendix for a working paper. I want to learn how an office turns "
                   "that into a view."),
    resume_experience=[dict(entry=1, bullets=[
        "Assemble and document panel datasets for two faculty housing studies, "
        "reconciling series that three public sources report on different bases.",
        "Maintain cleaning and merge scripts a supervisor can rerun, so each table "
        "in a draft traces to its source file.",
        "Drafted the data appendix for a working paper, stating each adjustment "
        "and its assumptions.",
    ])],
    resume_projects=[
        dict(key="rents_and_transit",
             line="Study of advertised rents along a new rail corridor, reported "
                  "against several definitions of the comparison area."),
        dict(key="vanilla",
             line="Options-pricing library that returns its assumptions alongside "
                  "the price."),
    ],
    notes="",
)


class FakeClaude:
    """Stands in for llm.call. Script it with packages and reviews in order;
    the last one of each repeats. Any other schema is scripted through
    `others`, keyed by the schema's class name. Records every call so tests can
    assert on what was asked and how many times."""

    def __init__(self, packages=None, reviews=None, others=None):
        from apply import llm

        self.packages = list(packages or [llm.Package(**CLEAN)])
        self.reviews = list(reviews or [self.review()])
        self.others: dict[str, list] = {name: list(queue) for name, queue in (others or {}).items()}
        self.calls: list[tuple[str, list, str]] = []

    @staticmethod
    def review(**overrides):
        from apply import llm

        base = dict(verdict="send", unsupported_claims=[], authorization_correct=True,
                    cites_posting_specifically=True, findings=[],
                    strongest_sentence="x", weakest_sentence="y")
        base.update(overrides)
        findings = [llm.Finding(**f) if isinstance(f, dict) else f
                    for f in base.pop("findings")]
        return llm.Review(findings=findings, **base)

    @staticmethod
    def package(**overrides):
        from apply import llm

        return llm.Package(**{**CLEAN, **overrides})

    def __call__(self, *, system, user, schema, model, effort, **kwargs):
        from apply import llm

        self.calls.append((schema.__name__, system, user))
        if schema is llm.Package:
            queue = self.packages
        elif schema is llm.Review:
            queue = self.reviews
        else:
            queue = self.others.get(schema.__name__)
            if not queue:
                raise AssertionError(f"FakeClaude has nothing scripted for {schema.__name__}")
        result = queue.pop(0) if len(queue) > 1 else queue[0]
        return result, llm.Usage(model, input_tokens=6000, output_tokens=3000)

    def count(self, name: str) -> int:
        return sum(1 for schema, _, _ in self.calls if schema == name)


@pytest.fixture
def fake_claude():
    return FakeClaude
