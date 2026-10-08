"""Job description -> track, by keyword scoring.

Deterministic on purpose. The owner should be able to read the matched keywords
and immediately see why a posting landed where it did, and override it when the
scoring is wrong. A model that cannot be argued with is worse than one that can.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from .models import Track


@dataclass(slots=True)
class Classification:
    track: Track
    scores: dict
    matched: dict = field(default_factory=dict)
    tied: bool = False
    #: The track a tie or a blank resolves to, for `why` to name.
    default: str = "corporate"

    @property
    def why(self) -> str:
        """One line the owner can read and disagree with."""
        hits = self.matched.get(self.track, [])
        if not hits:
            return f"{self.track} (no keywords matched; defaulted)"
        if self.tied:
            return f"{self.track} (tie broken toward {self.default}) — {', '.join(hits)}"
        return f"{self.track} ({self.scores[self.track]}) — {', '.join(hits)}"

    def table(self) -> list[tuple[str, int, str]]:
        return [(str(t), self.scores[t], ", ".join(self.matched.get(t, [])) or "—")
                for t in sorted(self.scores, key=lambda t: -self.scores[t])]


def _pattern(phrase: str) -> re.Pattern:
    """Match the phrase on non-alphanumeric boundaries, so 'quant' does not fire
    inside 'quantify' but 'c++' and 'm&a' still match."""
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(phrase)}(?![A-Za-z0-9])", re.I)


@lru_cache(maxsize=8)
def _compiled(tracks: tuple) -> dict:
    """(phrase, weight, pattern) per track. The phrases and weights live in the
    `tracks` block of search.defaults.yaml, or the user's data/search.yaml.
    Multi-word phrases outscore single words because a single word like "risk"
    or "valuation" shows up in nearly every finance posting."""
    return {Track(spec.name): [(p, w, _pattern(p)) for p, w in spec.keywords]
            for spec in tracks}


def classify(text: str, config=None) -> Classification:
    from .search import load

    config = config or load()
    scores: dict[Track, int] = {}
    matched: dict[Track, list[str]] = {}

    for track, signals in _compiled(config.tracks).items():
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
    # Ties resolve to the default track (corporate, unless configured otherwise):
    # it is the least over-claiming thing to be wrong about.
    track = Track(config.default_track) if tied else leaders[0]
    return Classification(track=track, scores=scores, matched=matched, tied=tied,
                          default=config.default_track)
