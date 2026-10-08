from __future__ import annotations

import yaml

SWE = {"tracks": {"default": "swe", "kinds": {
    "swe": {"resume": "projects_first", "code_link": True,
            "keywords": [["software engineer", 5], ["backend", 3], ["python", 2]]},
    "data": {"resume": "experience_first", "code_link": False,
             "keywords": [["data analyst", 5], ["sql", 3], ["tableau", 3]]}}}}


def _use(isolated_data_dir, body):
    from apply import search
    (isolated_data_dir / "search.yaml").write_text(yaml.safe_dump(body), encoding="utf-8")
    search._load_cached.cache_clear()


def test_defaults_are_todays_four_tracks():
    from apply import search
    cfg = search.load()
    assert [t.name for t in cfg.tracks] == ["quant", "banking", "allocator", "corporate"]
    assert cfg.default_track == "corporate"
    assert cfg.track("quant").resume == "projects_first" and cfg.track("quant").code_link
    assert not cfg.track("banking").code_link


def test_defaults_carry_todays_keyword_weights():
    from apply import search
    quant = dict(search.load().track("quant").keywords)
    assert quant["market making"] == 5 and quant["python"] == 1 and quant["pricing model"] == 4


def test_configured_tracks_replace_the_defaults(isolated_data_dir):
    from apply.classify import classify
    _use(isolated_data_dir, SWE)
    assert classify("Backend software engineer, Python").track == "swe"
    assert classify("Data analyst: SQL and Tableau").track == "data"
    assert classify("nothing relevant").track == "swe"


def test_track_parse_follows_the_config(isolated_data_dir):
    import pytest
    from apply.models import Track
    with pytest.raises(ValueError, match="expected one of: quant, banking, allocator, corporate"):
        Track.parse("swe")
    _use(isolated_data_dir, SWE)
    assert Track.parse("SWE") == "swe"


def test_a_custom_track_renders_through_the_generic_letter(isolated_data_dir, workspace, profile, quillon_jd):
    from conftest import posting_from
    from apply import generate
    _use(isolated_data_dir, SWE)
    assert generate.select_resume("swe") == "resume_quant"
    assert generate.select_resume("data") == "resume_traditional"
    posting = posting_from(quillon_jd, track="swe")
    letter = generate.Letter(**_letter_kwargs())
    tex = generate.render_letter(profile, posting, letter)
    assert "One." in tex and "Four." in tex


def _letter_kwargs():
    """The smallest valid Letter: four paragraphs, a closing, the frame."""
    return {"paragraphs": ["One.", "Two.", "Three.", "Four."],
            "closing": "Thank you for your time.",
            "salutation": "Dear Hiring Committee,",
            "signoff": "Sincerely,"}
