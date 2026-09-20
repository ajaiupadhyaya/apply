"""The profile loader. Everything a generated document says passes through here."""

from __future__ import annotations

import pytest

from apply.profile import ASK, Profile, ProfileError, deep_merge


def test_deep_merge_overlays_without_flattening():
    base = {"a": {"x": 1, "y": 2}, "b": 3}
    assert deep_merge(base, {"a": {"y": 9}}) == {"a": {"x": 1, "y": 9}, "b": 3}


def test_the_private_overlay_wins(workspace):
    (workspace / "data" / "profile.private.yaml").write_text(
        "identity:\n  phone: '555'\n  email: override@example.com\n"
    )
    profile = Profile.load()
    assert profile.phone == "555"
    assert profile.email == "override@example.com"
    assert profile.legal_name == "Ajai Upadhyaya"   # untouched by the overlay


def test_graduation_is_read_from_the_authoritative_field(profile):
    assert profile.grad_expected == (2027, 5)
    assert profile.grad_month_year == "May 2027"
    assert profile.grad_season_year == "spring 2027"
    assert profile.grad_year == 2027


def test_display_name_uses_the_preferred_first_name(profile):
    assert profile.display_name == "AJ Upadhyaya"
    assert profile.legal_name == "Ajai Upadhyaya"
    assert profile.file_name == "AJ_Upadhyaya"


def test_the_confirmed_sponsorship_answer(profile):
    assert profile.work_authorized is True
    assert profile.needs_sponsorship_ever is False


def test_ask_values_are_reported(profile):
    assert "experience[0].start" in profile.unresolved()


def test_require_resolved_raises_on_an_ask(profile):
    with pytest.raises(ProfileError, match="still ASK"):
        profile.require_resolved("experience")


def test_projects_are_gated_by_track(profile):
    assert [p.key for p in profile.projects_for("quant")] == [
        "ohcamel", "compute_index", "basis"]
    assert "ohcamel" not in [p.key for p in profile.projects_for("banking")]


def test_sourced_tokens_include_the_graduation_date(profile):
    assert "2027" in profile.sourced_tokens
    assert "4200000" not in profile.sourced_tokens


def test_a_missing_profile_says_what_to_do(tmp_path, monkeypatch):
    monkeypatch.setenv("APPLY_DATA_DIR", str(tmp_path))
    with pytest.raises(ProfileError, match="apply init"):
        Profile.load()
