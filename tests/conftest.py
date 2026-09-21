"""Test fixtures.

Every test runs against a temporary data directory and a temporary out/, so the
suite can never touch the owner's real apply.db, profile, or generated letters.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """An isolated data dir (with the real profile) and an isolated out/."""
    data = tmp_path / "data"
    data.mkdir()
    shutil.copy(REPO / "data" / "profile.yaml", data / "profile.yaml")
    out = tmp_path / "out"
    out.mkdir()

    monkeypatch.setenv("APPLY_DATA_DIR", str(data))
    monkeypatch.setenv("APPLY_OUT_DIR", str(out))
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
def blackrock_jd() -> str:
    return (FIXTURES / "blackrock.txt").read_text()


@pytest.fixture
def vcimco_jd() -> str:
    return (FIXTURES / "vcimco.txt").read_text()


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
    from apply import llm

    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(llm, "_profile_dir", lambda: tmp_path / "no-anthropic-profile")
    monkeypatch.setattr(llm, "_keychain_key", lambda: None)

    def tripwire(**_):
        raise AssertionError("a test tried to call the real Anthropic API")

    monkeypatch.setattr(llm, "call", tripwire)


CLEAN = dict(
    paragraph_1=("I am applying for the Investment Intern role at VCIMCO. I study "
                 "Finance at Virginia Commonwealth University and graduate in May "
                 "2027, and the Investment Committee is why this one."),
    paragraph_2=("At the University of Virginia I advise faculty and graduate "
                 "researchers on Bloomberg Terminal, WRDS and Morningstar Direct. "
                 "Most of the work is resolving cross-vendor data discrepancies: "
                 "two vendors disagree about the same series, and someone has to "
                 "find out which convention each is using before the number is used."),
    paragraph_3=("I also write BASIS, a biweekly research report on finance, "
                 "economics and technology, and I built an independent price index "
                 "for GPU compute rental markets."),
    paragraph_4=("The draw is the Investment Committee. An office that holds a view "
                 "across managers and asset classes needs someone careful with the "
                 "data underneath it, and that is the work I already do."),
    closing=("I am authorized to work in the United States and will not require "
             "sponsorship, now or in the future. I would welcome the chance to talk."),
    proof_asset="The UVA consulting role",
    anchor_used="the Investment Committee",
    why_role_short=("The posting asks for careful work on the data the investment "
                    "team relies on, which is what I do now for researchers at UVA."),
    why_role_long=("The posting asks for careful work on the data the investment team "
                   "relies on for asset allocation, and for writing that goes to the "
                   "Investment Committee. I already resolve data discrepancies for "
                   "faculty and graduate researchers, and I write BASIS to a standing "
                   "deadline. I want to learn how an office turns that into a view."),
    notes="",
)


class FakeClaude:
    """Stands in for llm.call. Script it with packages and reviews in order;
    the last one of each repeats. Records every call so tests can assert on
    what was asked and how many times."""

    def __init__(self, packages=None, reviews=None):
        from apply import llm

        self.packages = list(packages or [llm.Package(**CLEAN)])
        self.reviews = list(reviews or [self.review()])
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

    def __call__(self, *, system, user, schema, model, effort):
        from apply import llm

        self.calls.append((schema.__name__, system, user))
        queue = self.packages if schema is llm.Package else self.reviews
        result = queue.pop(0) if len(queue) > 1 else queue[0]
        return result, llm.Usage(model, input_tokens=6000, output_tokens=3000)

    def count(self, name: str) -> int:
        return sum(1 for schema, _, _ in self.calls if schema == name)


@pytest.fixture
def fake_claude():
    return FakeClaude
