"""Job description -> track, by keyword scoring.

Deterministic on purpose. The owner should be able to read the matched keywords
and immediately see why a posting landed where it did, and override it when the
scoring is wrong. A model that cannot be argued with is worse than one that can.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .models import Track

#: (phrase, weight). Multi-word phrases outscore single words because a single
#: word like "risk" or "valuation" shows up in nearly every finance posting.
SIGNALS: dict[Track, list[tuple[str, int]]] = {
    Track.QUANT: [
        ("market making", 5), ("market-making", 5), ("quantitative", 4),
        ("quant", 4), ("systematic", 4), ("backtest", 4), ("aladdin", 4),
        ("low latency", 4), ("high frequency", 4), ("ocaml", 4),
        ("trading", 3), ("derivatives", 3), ("alpha", 3), ("stochastic", 3),
        ("research associate", 3), ("c++", 3), ("signal", 2), ("volatility", 2),
        ("risk management", 3), ("risk", 2), ("execution", 2), ("python", 1),
        ("portfolio construction", 2), ("time series", 3), ("statistical", 2),
        ("hedging", 3), ("attribution", 2), ("exposure", 2), ("var", 3),
        ("factor model", 4), ("pricing model", 4),
    ],
    Track.BANKING: [
        ("investment banking", 5), ("mergers and acquisitions", 5),
        ("leveraged buyout", 5), ("comparable company", 5), ("pitchbook", 5),
        ("deal execution", 4), ("m&a", 4), ("lbo", 4), ("sell-side", 3),
        ("sell side", 3), ("buy-side advisory", 3), ("private capital", 3),
        ("private equity", 3), ("coverage group", 3), ("dcf", 3),
        ("discounted cash flow", 4), ("pitch", 3), ("corporate development", 4),
        ("transaction", 2), ("valuation", 2), ("financial modeling", 2),
        ("coverage", 2), ("capital raise", 4), ("restructuring", 3),
    ],
    Track.ALLOCATOR: [
        ("fund of funds", 5), ("asset allocation", 5), ("manager selection", 5),
        ("manager research", 5), ("investment office", 5), ("endowment", 4),
        ("ocio", 4), ("outsourced chief investment", 5), ("allocator", 4),
        ("limited partner", 3), ("institutional investing", 3), ("foundation", 3),
        ("pension", 3), ("capital markets assumptions", 4), ("due diligence", 2),
        ("asset classes", 3), ("investment committee", 3), ("long-term pool", 4),
        ("general partner", 2), ("endowment model", 5),
        ("investment team", 3), ("investment office", 4), ("custodian", 3),
        ("investment review", 3), ("asset owner", 4), ("portfolio operations", 3),
        ("portfolio managers", 2), ("separate account", 3), ("mandate", 2),
    ],
    Track.CORPORATE: [
        ("financial planning and analysis", 5), ("fp&a", 5),
        ("variance analysis", 5), ("rotational program", 5), ("month-end close", 5),
        ("rotational", 3), ("budgeting", 3), ("controller", 3), ("treasury", 3),
        ("business analyst", 3), ("management reporting", 3),
        ("corporate finance", 3), ("cost center", 3), ("forecasting", 2),
        ("accounting", 2), ("business partner", 2), ("operating plan", 3),
        ("reconciliation", 3), ("reconcile", 3), ("close process", 4),
        ("general ledger", 4), ("expense", 2), ("procurement", 3),
    ],
}


@dataclass(slots=True)
class Classification:
    track: Track
    scores: dict[Track, int]
    matched: dict[Track, list[str]] = field(default_factory=dict)
    tied: bool = False

    @property
    def why(self) -> str:
        """One line the owner can read and disagree with."""
        hits = self.matched.get(self.track, [])
        if not hits:
            return f"{self.track.value} (no keywords matched; defaulted)"
        if self.tied:
            return f"{self.track.value} (tie broken toward corporate) — {', '.join(hits)}"
        return f"{self.track.value} ({self.scores[self.track]}) — {', '.join(hits)}"

    def table(self) -> list[tuple[str, int, str]]:
        return [
            (t.value, self.scores[t], ", ".join(self.matched.get(t, [])) or "—")
            for t in sorted(Track, key=lambda t: -self.scores[t])
        ]


def _pattern(phrase: str) -> re.Pattern:
    """Match the phrase on non-alphanumeric boundaries, so 'quant' does not fire
    inside 'quantify' but 'c++' and 'm&a' still match."""
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(phrase)}(?![A-Za-z0-9])", re.I)


_COMPILED = {t: [(p, w, _pattern(p)) for p, w in sig] for t, sig in SIGNALS.items()}


def classify(text: str) -> Classification:
    scores: dict[Track, int] = {}
    matched: dict[Track, list[str]] = {}

    for track, signals in _COMPILED.items():
        total = 0
        hits: list[str] = []
        for phrase, weight, pattern in signals:
            n = len(pattern.findall(text))
            if n:
                # Repetition is evidence, but with sharply diminishing returns —
                # otherwise a posting that says "trading" nine times drowns out
                # one that says "outsourced chief investment officer" once.
                total += weight * min(n, 3)
                hits.append(phrase)
        scores[track] = total
        matched[track] = hits

    best = max(scores.values())
    leaders = [t for t, s in scores.items() if s == best]
    tied = len(leaders) > 1 or best == 0
    # Ties resolve to corporate: it is the least over-claiming thing to be wrong about.
    track = Track.CORPORATE if tied else leaders[0]
    return Classification(track=track, scores=scores, matched=matched, tied=tied)
