"""The unattended pass, and the ceiling on what it may spend.

Offline throughout: the adapters are stubbed, because what these tests protect
is the pipeline's arithmetic — what gets deduped, what gets stored, what never
reaches a document — not whether Greenhouse is up.
"""

from __future__ import annotations

import pytest

from apply import db, discover
from apply.budget import Budget, BudgetExceeded
from apply.llm import Usage
from apply.sources.base import RawPosting

BODY = "Undergraduate students graduating in 2027 are encouraged to apply. " * 14


def posting(title="Investment Analyst", location="New York, NY", employer="Acme",
            body=BODY, source="greenhouse", priority=1):
    return RawPosting(employer=employer, title=title, url="https://x/1", source=source,
                      location=location, description=body, employer_priority=priority)


class Stub:
    """An adapter that returns what the test hands it."""

    name = "greenhouse"

    def __init__(self, postings):
        self.postings = postings
        self.hydrated = 0

    def fetch(self, config):
        return list(self.postings)

    def hydrate(self, p, config):
        self.hydrated += 1
        return p


@pytest.fixture
def stubbed(monkeypatch):
    def install(postings):
        stub = Stub(postings)
        monkeypatch.setitem(discover.ADAPTERS, "greenhouse", stub)
        return stub
    return install


EMPLOYERS = [{"name": "Acme", "ats": "greenhouse", "board": "acme", "priority": 1}]


# -------------------------------------------------------------- dedupe

def test_the_same_role_twice_is_stored_once(conn, stubbed):
    stubbed([posting(), posting()])
    result = discover.run(conn, employers=EMPLOYERS)
    assert result.fetched == 2
    assert result.unique == 1
    assert len(result.created) == 1


def test_the_richer_copy_wins_a_duplicate():
    thin = posting(body="short")
    rich = posting(body=BODY)
    assert discover.dedupe([thin, rich])[0].description == BODY
    assert discover.dedupe([rich, thin])[0].description == BODY


def test_a_second_pass_finds_nothing_new(conn, stubbed):
    stubbed([posting()])
    first = discover.run(conn, employers=EMPLOYERS)
    second = discover.run(conn, employers=EMPLOYERS)
    assert len(first.created) == 1
    assert second.already_known == 1
    assert second.created == []


# ------------------------------------------------------------- the gate

def test_rejects_never_become_postings(conn, stubbed):
    stubbed([
        posting(title="Senior Analyst"),
        posting(title="Software Engineer"),
        posting(title="Investment Analyst", location="London, United Kingdom"),
    ])
    result = discover.run(conn, employers=EMPLOYERS)
    assert result.rejected == 3
    assert result.created == []
    assert db.rows(conn) == []


def test_a_survivor_is_stored_with_its_score_and_reasons(conn, stubbed):
    stubbed([posting()])
    result = discover.run(conn, employers=EMPLOYERS)
    stored = db.get_posting(conn, result.created[0])
    assert stored.score and stored.score_verdict in ("pursue", "maybe")
    assert stored.score_reasons and stored.fingerprint and stored.discovered_at


def test_the_verbatim_posting_text_is_kept(conn, stubbed):
    stubbed([posting()])
    result = discover.run(conn, employers=EMPLOYERS)
    assert BODY.strip()[:60] in db.get_posting(conn, result.created[0]).jd_raw


def test_dry_run_writes_nothing(conn, stubbed):
    stubbed([posting()])
    result = discover.run(conn, employers=EMPLOYERS, dry_run=True)
    assert result.worth_reading
    assert result.created == []
    assert db.rows(conn) == []


# ------------------------------------------------------------ hydration

def test_only_survivors_are_hydrated(conn, stubbed):
    """The expensive half runs on what is left, not on what arrived."""
    stub = stubbed([posting(body=""), posting(title="Senior Analyst", body="")])
    discover.run(conn, employers=EMPLOYERS, hydrate_limit=10)
    assert stub.hydrated == 1


def test_the_hydration_budget_is_spent_only_on_postings_that_need_it(conn, stubbed):
    """A pre-hydrated posting must not consume an allowance slot.

    Greenhouse returns descriptions inline and Workday does not, so a naive
    top-N loop spends its whole budget skipping Greenhouse rows and never
    reaches the Workday ones — whose deadlines only appear on hydration.
    """
    already = [posting(title=f"Investment Analyst {i}") for i in range(6)]
    empty = [posting(title=f"Research Analyst {i}", body="") for i in range(3)]
    stub = stubbed(already + empty)
    discover.run(conn, employers=EMPLOYERS, hydrate_limit=3)
    assert stub.hydrated == 3


def test_hydration_respects_its_limit(conn, stubbed):
    stub = stubbed([posting(title=f"Investment Analyst {i}", body="") for i in range(8)])
    discover.run(conn, employers=EMPLOYERS, hydrate_limit=3)
    assert stub.hydrated == 3


# -------------------------------------------------------------- failure

def test_one_broken_source_does_not_stop_the_run(conn, stubbed, monkeypatch):
    stubbed([posting()])

    class Broken:
        name = "lever"
        def fetch(self, config):
            raise discover.SourceError("lever/beta: 503")
        def hydrate(self, p, config):
            return p

    monkeypatch.setitem(discover.ADAPTERS, "lever", Broken())
    result = discover.run(conn, employers=[
        *EMPLOYERS, {"name": "Beta", "ats": "lever", "board": "beta"}])
    assert len(result.created) == 1
    assert any("503" in e for e in result.errors)


def test_an_unknown_ats_is_reported_not_raised(conn):
    result = discover.run(conn, employers=[{"name": "X", "ats": "nonsense"}])
    assert any("unknown ats" in e for e in result.errors)


def test_no_employers_says_what_to_do(conn):
    assert any("employers.example.yaml" in e for e in discover.run(conn, employers=[]).errors)


# --------------------------------------------------------------- budget

def test_the_per_call_ceiling_refuses(conn):
    budget = Budget(conn, caps={"per_call_usd": 0.20, "per_run_usd": 5, "monthly_usd": 5})
    with pytest.raises(BudgetExceeded, match="per-call"):
        budget.check(0.35, "write")


def test_the_per_run_ceiling_refuses(conn):
    budget = Budget(conn, caps={"per_call_usd": 1, "per_run_usd": 0.30, "monthly_usd": 5})
    budget.record(Usage("claude-opus-5", 5000, 3300), "write", "a")   # ~$0.107
    budget.record(Usage("claude-opus-5", 5000, 3300), "write", "b")
    with pytest.raises(BudgetExceeded, match="per-run"):
        budget.check(0.15, "write")


def test_the_monthly_ceiling_refuses(conn):
    budget = Budget(conn, caps={"per_call_usd": 1, "per_run_usd": 99, "monthly_usd": 0.15})
    budget.record(Usage("claude-opus-5", 5000, 3300), "write", "a")
    with pytest.raises(BudgetExceeded, match="monthly"):
        budget.check(0.10, "write")


def test_spend_is_attributed_by_purpose(conn):
    budget = Budget(conn)
    budget.record(Usage("claude-opus-5", 5000, 3300), "write", "a")
    budget.record(Usage("claude-haiku-4-5", 2000, 200), "score", "b")
    purposes = {row[0] for row in budget.by_purpose()}
    assert purposes == {"write", "score"}
    assert budget.state().calls == 2


def test_a_fresh_ledger_starts_at_zero(conn):
    state = Budget(conn).state()
    assert state.month_to_date == 0 and state.remaining == state.monthly_cap
