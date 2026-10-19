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


def test_slug_candidates_never_fall_back_to_a_bare_first_word():
    assert "two" not in resolve.slug_candidates("Two Sigma")
    assert "man" not in resolve.slug_candidates("Man Group")
    assert resolve.slug_candidates("Jane Street") == ["janestreet", "jane-street"]


def test_as_entry_and_as_yaml_share_the_caps():
    for ats, cap in resolve.MAX_RESULTS.items():
        c = resolve.Candidate(ats, "", {"host": "h", "site": "s", "tenant": "t"}, True)
        assert c.as_entry("X", 3, ["a"], [])["max_results"] == cap
        assert f"max_results: {cap}" in c.as_yaml("X")
    assert resolve.Candidate("oracle", "", {"host": "h", "site": "s"}, True).as_entry("X", 3, ["a"], [])["search"] == ["a"]


def test_verify_is_none_when_the_adapter_raises(monkeypatch):
    from apply.sources import ADAPTERS

    def boom(config):
        raise RuntimeError("down")

    monkeypatch.setattr(ADAPTERS["greenhouse"], "fetch", boom)
    assert resolve.verify(resolve.Candidate("greenhouse", "", {"board": "x"}, True)) is None
