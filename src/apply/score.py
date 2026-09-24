"""Is this posting worth a letter?

This runs on every posting a discovery pass finds, and it costs nothing. That is
the point: a Workday employer returns four hundred openings, of which maybe three
are plausible, and paying a model to read the other three hundred and ninety-seven
is how a twenty-dollar budget disappears in a week.

So the order is: reject for free, score for free, and only then spend anything.
A posting that survives this gate has already passed a seniority check, a
geography check, a function check, and a degree-requirement check.

Every rejection carries its reason, because a gate you cannot argue with is a
gate you will eventually route around.

What this file holds is the algorithm. What it no longer holds is the
vocabulary — which cities count, which titles are the wrong function, what a
quantitative research role is worth. That is one person's search, not everyone's,
so it lives in search.defaults.yaml and is overridable per block in
data/search.yaml. See `apply search`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from .classify import classify
from .search import SearchConfig
from .sources.base import RawPosting


class Verdict(str, Enum):
    PURSUE = "pursue"     # write the letter
    MAYBE = "maybe"       # borderline; worth a cheap model's opinion
    REJECT = "reject"     # never reaches a document


#: How each configured reject block words itself. A block the configuration adds
#: that is not named here falls back to its own name.
_REJECT_REASON = {
    "seniority": "title is senior",
    "off_function": "off-function",
    "too_technical": "engineering role",
    "graduate_program": "for graduate students",
}
#: …and what it is filed under. These strings reach the database and the web UI.
_REJECT_LABEL = {
    "seniority": "seniority",
    "off_function": "function",
    "too_technical": "technical",
    "graduate_program": "degree",
}


# --------------------------------------------------- algorithm, not vocabulary
#
# The rules below are not about one person's field or city, so they stay here:
# an experience bar, a credential bar, and the eligibility window a campus
# programme states in its own words.

#: Experience and credential bars an undergraduate cannot clear.
YEARS = re.compile(r"(\d+)\s*\+?\s*(?:-\s*\d+\s*)?years?(?:\s+of)?\s+(?:relevant\s+|professional\s+|work\s+)?experience", re.I)
ADVANCED_DEGREE = re.compile(
    r"(ph\.?d|doctorate|mba|master'?s|graduate\s+degree|advanced\s+degree)[^.]{0,40}"
    r"(required|is\s+required|must\s+have|mandatory)", re.I)
#: A title naming a graduate programme is aimed at graduate students, whatever
#: the body says: "Quantitative Analyst, Ph.D. Intern" scored 92 in a live pass.
#: Pre-doctoral roles are the opposite — built for undergraduates — so they pass.
#: This one is a hand-built alternation rather than a list of tokens, which is
#: why it did not move into the configuration with the other rejects.
GRADUATE_PROGRAM = re.compile(
    r"\bph\.?\s?d\b|\bmba\b|\bmaster'?s\s+(?:intern|student|program)"
    r"|\bpost[\s-]?doc\w*|\b(?<!pre\s)(?<!pre-)doctoral\b", re.I)

#: "Expected graduation date of December 2027 – June 2028". Every bank's
#: summer programme states one, and it is the real eligibility line: a May 2027
#: graduate is outside every 2027 summer analyst window and inside every 2027
#: full-time one. Found by the writer, one letter in, not by the gate.
_MONTH = (r"\b(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|"
          r"aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|"
          r"spring|summer|fall|autumn|winter)\s+(20\d\d)\b")
GRAD_WINDOW = re.compile(
    rf"graduat\w*[^.\n]{{0,60}}?{_MONTH}\s*(?:–|—|-|to|through|thru|until|and|or)\s*{_MONTH}",
    re.I)
_MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7,
           "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}
#: A season as a bound: its first month opening a window, its last closing one.
_SEASONS = {"spring": (1, 5), "summer": (6, 8), "fall": (9, 12), "autumn": (9, 12),
            "winter": (12, 12)}


def _bound(word: str, year: str, *, closing: bool) -> tuple[int, int]:
    word = word.lower()
    if word in _SEASONS:
        first, last = _SEASONS[word]
        return int(year), last if closing else first
    return int(year), _MONTHS[word[:3]]


def graduation_window(body: str) -> tuple[tuple[int, int], tuple[int, int], str] | None:
    """The (year, month) range a posting says its hires graduate in, if it says."""
    match = GRAD_WINDOW.search(body or "")
    if not match:
        return None
    start = _bound(match.group(1), match.group(2), closing=False)
    end = _bound(match.group(3), match.group(4), closing=True)
    if end < start:
        return None                                   # a misread, not a window
    return start, end, match.group(0)


def _us_location_pattern() -> re.Pattern:
    from .parse import _STATE_ALT

    return re.compile(rf"united\s+states|\busa?\b|,\s*(?:{_STATE_ALT})\b", re.I)


_US_LOCATION = _us_location_pattern()


def _senior_grade(posting: RawPosting, title: str) -> str | None:
    """A rank this employer itself calls senior. "Analyst III" means nothing
    without the registry entry that says what III is worth at this firm."""
    for grade in posting.employer_senior_grades:
        if re.search(rf"(?<![A-Za-z0-9]){re.escape(grade)}(?![A-Za-z0-9])", title, re.I):
            return grade
    return None


@dataclass(slots=True)
class Score:
    value: int
    verdict: Verdict
    reasons: list[str] = field(default_factory=list)
    rejected_by: str | None = None
    track: str = "corporate"

    @property
    def pursue(self) -> bool:
        return self.verdict is Verdict.PURSUE

    def __str__(self) -> str:
        head = f"{self.verdict.value} {self.value}"
        return f"{head} — {'; '.join(self.reasons)}" if self.reasons else head


def thresholds_in_force(config: SearchConfig, preferences: dict | None = None) -> dict[str, int]:
    """The pursue and maybe bars this run will actually use.

    Two files can set them: search.defaults.yaml or its data/search.yaml
    override, and the profile's own `search:` block — which is the one
    profile.private.example.yaml documents, so it is the one most people edit.
    The profile wins. Anything that wants to *print* the bar has to come through
    here too, or it prints a number the gate is not using.
    """
    return {**config.thresholds, **((preferences or {}).get("thresholds") or {})}


def score(posting: RawPosting, preferences: dict | None = None,
          standing: str | None = None, config: SearchConfig | None = None) -> Score:
    """Relevance only. Urgency is the digest's job, not this function's."""
    from . import search as search_mod

    config = config or search_mod.load()
    preferences = preferences or {}
    standing = standing or preferences.get("class_standing")
    thresholds = thresholds_in_force(config, preferences)
    title = posting.title or ""
    location = posting.location or ""
    body = posting.description or ""
    reasons: list[str] = []

    def reject(why: str, by: str) -> Score:
        return Score(0, Verdict.REJECT, [why], rejected_by=by)

    # --- hard gates, cheapest first -------------------------------------
    # The reject blocks run in the order the configuration lists them. The
    # firm's own senior grades are part of the seniority check and run with it;
    # a configuration that drops the seniority block has turned both off.
    for name, pattern in config.rejects.items():
        hit = pattern.search(title)
        if hit:
            reason = _REJECT_REASON.get(name, name.replace("_", " "))
            return reject(f"{reason}: {hit.group(0)!r}", _REJECT_LABEL.get(name, name))
        if name == "seniority" and (grade := _senior_grade(posting, title)):
            return reject(f"{grade!r} is a senior grade at {posting.employer}", "seniority")
    if GRADUATE_PROGRAM.search(title):
        return reject(f"for graduate students: {GRADUATE_PROGRAM.search(title).group(0)!r}",
                      "degree")

    if standing:
        for year, pattern in config.class_scoped.items():
            hit = pattern.search(title)
            if hit and year != standing:
                return reject(
                    f"aimed at {year} students; you are a {standing}"
                    f" ({hit.group(0)!r})", "class year")

    # Places, in the order the configuration lists them: the first match is the
    # one that scores. A posting matching none of them may still be refused for
    # being somewhere else entirely.
    places = [(label, weight) for _, label, weight, pattern, in_title in config.geography
              if pattern.search(location) or (in_title and pattern.search(title))]
    if not places:
        if config.non_us.search(location):
            return reject(
                f"outside the US: {location!r}" if config.assume_us
                else f"somewhere this search does not cover: {location!r}", "geography")
        # LinkedIn writes bare cities ("Chantilly"), so an unrecognised name on
        # its own is neutral. Only a "City, Region" form whose region is plainly
        # not American is refused — "Boise, Idaho" passes, "Kyiv, Ukraine" does not.
        # That last step is the one piece of geography the gate knows by heart
        # rather than from the configuration, so it runs only for a search that
        # says it is in the United States. For any other country the shipped
        # vocabulary has nothing true to say, and silence beats a wrong refusal.
        if (config.assume_us and location and "," in location
                and not _US_LOCATION.search(location)):
            return reject(f"location not recognised as US: {location!r}", "geography")

    if body:
        years = YEARS.search(body)
        if years and int(years.group(1)) >= 3:
            return reject(f"asks for {years.group(1)}+ years of experience", "experience")
        degree = ADVANCED_DEGREE.search(body)
        if degree:
            return reject(f"requires an advanced degree: {degree.group(0)[:48]!r}", "degree")
        graduation = preferences.get("graduation")
        window = graduation_window(body) if graduation else None
        if window and not (window[0] <= tuple(graduation) <= window[1]):
            (y0, m0), (y1, m1), _ = window
            return reject(
                f"graduates {y0}-{m0:02d} to {y1}-{m1:02d}; you graduate "
                f"{graduation[0]}-{graduation[1]:02d}", "graduation")

    # --- positive signal -------------------------------------------------
    value = 0
    best_role = 0
    for pattern, weight in config.role_fit:
        if re.search(pattern, title, re.I):
            best_role = max(best_role, weight)
    if best_role:
        value += best_role
        reasons.append(f"role fit +{best_role}")
    else:
        # Nothing in the title says this is the kind of work. The body might, but
        # a title that gives no signal is usually not the job.
        value += 2

    haystack = f"{title}\n{body[:2000]}"
    timing_hit = 0
    for pattern, weight in config.timing:
        if re.search(pattern, haystack, re.I):
            timing_hit = max(timing_hit, weight)
    for pattern, weight in config.title_timing:
        if re.search(pattern, title, re.I):
            timing_hit = max(timing_hit, weight)
    if timing_hit:
        value += timing_hit
        reasons.append(f"timing +{timing_hit}")

    # The first place that matched, and only that one: the stated goal is the
    # heaviest single signal here, so it is listed first.
    if places:
        label, weight = places[0]
        value += weight
        reasons.append(f"{label} +{weight}")

    priority_bonus = {1: 12, 2: 8, 3: 4}.get(posting.employer_priority, 0)
    if priority_bonus:
        value += priority_bonus
        reasons.append(f"target firm +{priority_bonus}")

    classification = classify(haystack)
    track = classification.track.value
    if classification.scores[classification.track] >= 10:
        value += 8
        reasons.append(f"reads as {track} +8")
    if posting.employer_tracks and track in posting.employer_tracks:
        value += 4
        reasons.append("matches the firm's declared track +4")

    # A posting we have not hydrated yet cannot be trusted at the top of the
    # range — the body is where the disqualifiers live.
    if not posting.hydrated:
        value = min(value, thresholds["pursue"] + 9)
        reasons.append("not hydrated: capped pending the full description")

    value = max(0, min(100, value))
    if value >= thresholds["pursue"]:
        verdict = Verdict.PURSUE
    elif value >= thresholds["maybe"]:
        verdict = Verdict.MAYBE
    else:
        verdict = Verdict.REJECT
    return Score(value, verdict, reasons, track=track)
