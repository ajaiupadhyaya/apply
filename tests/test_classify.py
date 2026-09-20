"""Track classification. Deterministic and overridable, so the tests assert both
the outcome and the reason."""

from __future__ import annotations

from apply.classify import classify
from apply.models import Track


def test_blackrock_is_quant(blackrock_jd):
    result = classify(blackrock_jd)
    assert result.track is Track.QUANT
    assert "aladdin" in result.matched[Track.QUANT]


def test_vcimco_is_allocator(vcimco_jd):
    result = classify(vcimco_jd)
    assert result.track is Track.ALLOCATOR
    assert "manager research" in result.matched[Track.ALLOCATOR]


def test_deal_work_is_banking():
    text = ("M&A analyst. Deal execution, pitchbook preparation, comparable "
            "company analysis, LBO modeling, sell-side processes.")
    assert classify(text).track is Track.BANKING


def test_rotational_finance_is_corporate():
    text = ("Rotational program in corporate finance: FP&A, variance analysis, "
            "budgeting, management reporting.")
    assert classify(text).track is Track.CORPORATE


def test_nothing_matched_falls_back_to_corporate():
    result = classify("We are hiring someone nice.")
    assert result.track is Track.CORPORATE
    assert result.tied
    assert "defaulted" in result.why


def test_a_tie_resolves_to_corporate():
    """Corporate is the least over-claiming thing to be wrong about."""
    result = classify("")
    assert result.track is Track.CORPORATE


def test_word_boundaries_hold():
    """'quant' must not fire inside 'quantify', but 'c++' and 'm&a' must match."""
    assert "quant" not in classify("We quantify everything.").matched[Track.QUANT]
    assert "c++" in classify("Experience with C++ required.").matched[Track.QUANT]
    assert "m&a" in classify("M&A experience preferred.").matched[Track.BANKING]


def test_repetition_has_diminishing_returns():
    once = classify("trading")
    many = classify(" ".join(["trading"] * 40))
    assert many.scores[Track.QUANT] <= once.scores[Track.QUANT] * 3
