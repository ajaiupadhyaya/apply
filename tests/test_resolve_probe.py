from __future__ import annotations

from apply import resolve


def test_slug_candidates():
    assert resolve.slug_candidates("Jane Street Capital, LLC")[:3] == [
        "janestreetcapital", "jane-street-capital", "janestreet"]


def test_probe_returns_first_verified_board():
    seen = []

    def fake_verify(candidate, name="probe", search=None):
        seen.append((candidate.ats, candidate.config["board"]))
        return 12 if (candidate.ats, candidate.config["board"]) == ("lever", "acme") else None

    found = resolve.probe_slugs("Acme", verify_fn=fake_verify)
    assert found[0].ats == "lever" and found[1] == 12
    assert seen[0] == ("greenhouse", "acme")


def test_probe_gives_up_honestly():
    assert resolve.probe_slugs("Nobody", verify_fn=lambda c, name="p", search=None: None) is None


def test_entry_carries_the_users_search_terms():
    c = resolve.Candidate(ats="workday", evidence="", supported=True,
                          config={"host": "x.wd1.myworkdayjobs.com", "tenant": "x", "site": "X"})
    entry = c.as_entry("X Corp", 2, ["software engineer", "new grad"], ["swe"])
    assert entry["search"] == ["software engineer", "new grad"] and entry["tracks"] == ["swe"]
    assert 'search: ["software engineer", "new grad"]' in c.as_yaml("X Corp", search=["software engineer", "new grad"])


def test_as_yaml_defaults_and_eightfold_search():
    c = resolve.Candidate(ats="eightfold", evidence="", supported=True, config={"host": "x.eightfold.ai"})
    assert 'search: ["analyst", "intern", "2027"]' in c.as_yaml("X")
    assert 'search: ["quant"]' in c.as_yaml("X", search=["quant"])
    assert "search" not in resolve.Candidate("greenhouse", "", {"board": "x"}, True).as_entry("X", 3, ["a"], [])
