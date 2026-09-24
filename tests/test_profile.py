"""The profile loader. Everything a generated document says passes through here."""

from __future__ import annotations

import pytest

from apply.profile import Profile, ProfileError, deep_merge


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
    assert profile.legal_name == "Rachel Mercer"    # untouched by the overlay


def test_graduation_is_read_from_the_authoritative_field(profile):
    assert profile.grad_expected == (2027, 6)
    assert profile.grad_month_year == "June 2027"
    assert profile.grad_season_year == "summer 2027"
    assert profile.grad_year == 2027


def test_display_name_uses_the_preferred_first_name(profile):
    assert profile.display_name == "Rae Mercer"
    assert profile.legal_name == "Rachel Mercer"
    assert profile.file_name == "Rae_Mercer"


def test_the_confirmed_sponsorship_answer(profile):
    assert profile.work_authorized is True
    assert profile.needs_sponsorship_ever is False


def test_ask_values_are_reported(profile):
    assert "experience[0].start" in profile.unresolved()


def test_require_resolved_raises_on_an_ask(profile):
    with pytest.raises(ProfileError, match="still ASK"):
        profile.require_resolved("experience")


def test_projects_are_gated_by_track(profile):
    assert [p.key for p in profile.projects_for("banking")] == [
        "rents_and_transit", "vanilla"]
    assert "rents_and_transit" not in [p.key for p in profile.projects_for("quant")]


def test_sourced_tokens_include_the_graduation_date(profile):
    assert "2027" in profile.sourced_tokens
    assert "4200000" not in profile.sourced_tokens


def test_a_missing_profile_says_what_to_do(tmp_path, monkeypatch):
    monkeypatch.setenv("APPLY_DATA_DIR", str(tmp_path))
    with pytest.raises(ProfileError, match="apply setup"):
        Profile.load()


def test_class_standing_is_derived_not_stored(profile):
    """A stored year is wrong within a year and nobody updates it.

    Dates are pinned: asserting on "today" would start failing the day the
    fixture profile's owner graduates."""
    import datetime as dt

    assert profile.standing_on(dt.date(2026, 9, 21)) == "senior"   # graduates June 2027
    assert 0 < profile.years_to_graduation(dt.date(2026, 9, 21)) < 1
    assert profile.standing_on(dt.date(2025, 9, 1)) == "junior"
    assert profile.standing_on(dt.date(2027, 6, 1)) == "graduated"


def test_search_preferences_carry_the_derived_standing(profile):
    assert profile.search_preferences["class_standing"] == profile.class_standing
