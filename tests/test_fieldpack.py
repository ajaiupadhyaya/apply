"""The field pack. Mostly a test that nothing sensitive can get into it."""

from __future__ import annotations

import json

from apply.fieldpack import build, write
from conftest import posting_from

FORBIDDEN = ["ssn", "social security", "date of birth", "dob", "passport",
             "driver", "routing", "account number", "password", "api key"]


def _labels(pack) -> list[str]:
    return [label.lower() for f in pack["fields"] for label in f["labels"]]


def test_the_two_work_authorization_answers_are_present(profile, ashcombe_jd):
    pack = build(profile, posting_from(ashcombe_jd))
    values = {f["labels"][0]: f["value"] for f in pack["fields"]}
    assert values["Are you legally authorized to work in the United States?"] == "Yes"
    assert values["Will you now or in the future require sponsorship?"] == "No"


def test_graduation_comes_from_the_authoritative_field(profile, ashcombe_jd):
    pack = build(profile, posting_from(ashcombe_jd))
    values = {f["labels"][0]: f["value"] for f in pack["fields"]}
    assert values["Expected Graduation"] == profile.grad_month_year == "June 2027"


def test_nothing_sensitive_can_appear(profile, ashcombe_jd):
    pack = build(profile, posting_from(ashcombe_jd))
    serialized = json.dumps(pack).lower()
    for term in FORBIDDEN:
        # The omitted_by_design list names them on purpose; nothing else may.
        occurrences = serialized.count(term)
        named = json.dumps(pack["omitted_by_design"]).lower().count(term)
        assert occurrences == named, f"{term!r} leaked into the field pack"


def test_absent_private_facts_are_simply_omitted(profile, ashcombe_jd):
    """No profile.private.yaml in the test workspace, so no phone and no GPA."""
    pack = build(profile, posting_from(ashcombe_jd))
    assert "phone" not in _labels(pack)
    assert "gpa" not in _labels(pack)


def test_private_facts_appear_when_the_overlay_exists(workspace, ashcombe_jd):
    from apply.profile import Profile

    (workspace / "data" / "profile.private.yaml").write_text(
        "identity:\n  phone: '+1 555 555 0123'\neducation_private:\n  gpa: '3.87'\n"
    )
    pack = build(Profile.load(), posting_from(ashcombe_jd))
    values = {f["labels"][0]: f["value"] for f in pack["fields"]}
    assert values["Phone"] == "+1 555 555 0123"
    assert values["GPA"] == "3.87"


def test_the_per_application_answers_are_blank_until_written(profile, ashcombe_jd):
    pack = build(profile, posting_from(ashcombe_jd))
    keys = {e["key"]: e["answer"] for e in pack["essays"]}
    assert keys["why_this_firm_short"] == "" and keys["why_this_firm_long"] == ""


def test_claude_s_answers_reach_the_copy_buttons(profile, ashcombe_jd):
    pack = build(profile, posting_from(ashcombe_jd),
                 answers={"short": "Short answer.", "long": "Long answer."})
    keys = {e["key"]: e["answer"] for e in pack["essays"]}
    assert keys["why_this_firm_short"] == "Short answer."
    assert keys["why_this_firm_long"] == "Long answer."


def test_write_produces_readable_json(profile, ashcombe_jd, tmp_path):
    path = write(profile, posting_from(ashcombe_jd), tmp_path / "pack")
    assert json.loads(path.read_text())["slug"]
