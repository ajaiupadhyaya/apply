"""Write tests/fixtures/gate_corpus.json: the gate's vocabulary, exercised.

The committed corpus pins the relevance gate. It used to be one real pipeline,
anonymised — every firm's name cut out of the title, the employer column
replaced by a keyed hash. That was not enough, and could not be made enough. A
registry name is a name, but a firm is also its sub-brands, its products and its
office address, and a title that keeps any one of them names the firm as surely
as the registry does. Because the employer label groups rows, one surviving
brand identifies every other row of that employer — hundreds, for a large bank.
Cutting brand names one at a time is a denylist, and a denylist of private facts
is never finished.

So nothing here comes from anyone's pipeline. Every case is synthesised from
src/apply/search.defaults.yaml itself: for each configured pattern, a title or a
location built out of that pattern, scored by the current code, and frozen. The
firms are invented, the titles are assembled, and there is nothing to
deanonymise because there was never anything anonymised.

It pins the same thing the real corpus pinned, and rather better. The gate's
vocabulary moved from literals in score.py into YAML; the promise was that not
one verdict moved with it. A corpus of real postings tests that promise wherever
the postings happen to land — several hundred rows saying the same thing about
`\\banalyst\\b`, and nothing at all about `barista` or `\\bfpga\\b`. Read as the
gate reads them, the 826 real titles this replaced exercised 90 of the 228
configured entries, and not one of the seventeen in the seniority block. This
one has a case for every entry, near-misses for the boundaries and lookarounds a
transcription would quietly drop, and a coverage test that fails when the YAML
grows an entry this file has not been rerun against.

What each case carries, beyond the scored verdict:

  entry   the configured pattern it is built from, as [block, pattern]
  kind    "entry" when that pattern must match this case, "near-miss" when it
          must not, "algorithm" for a rule score.py keeps and the YAML does not

The near-misses are the half that catches a transcription: "Rising Senior
Summer Analyst" must not be refused as senior, "Basic Materials Equity Research"
must not be read as an ASIC job. A copy of the vocabulary that drops a
lookbehind or a word boundary still scores every positive case correctly and
fails these.

Run it after any edit to search.defaults.yaml:

    uv run python tools/synthesize_corpus.py

and read the diff: it is the list of verdicts your edit moved.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from apply import search
from apply.score import _REJECT_LABEL, score
from apply.sources.base import RawPosting

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "fixtures" / "gate_corpus.json"

#: The gate as the package ships it. The corpus is replayed against the same
#: thing, so that what it pins is the repository's behaviour and not the
#: behaviour of whatever data/search.yaml this machine happens to hold.
SHIPPED = search.load(Path("/nonexistent"))

#: One reader, held still, so that a change in the corpus is a change in the
#: gate. May 2027 and a senior: the class_scoped block is only consulted when a
#: standing is known, and the graduation window only when a date is.
GRADUATION = (2027, 5)
CLASS_STANDING = "senior"
PREFERENCES = {"graduation": GRADUATION, "class_standing": CLASS_STANDING}

#: Firms that do not exist, in the style of the two invented postings in
#: data/examples/. Nothing here is a real employer, and nothing here is on
#: anyone's list. They vary so that the corpus covers the priority bonus and
#: the employer columns, not because any of them means anything.
EMPLOYERS = [
    ("Quillon Asset Management", 1),
    ("Ashcombe Trust", 2),
    ("Fenwold Securities", 3),
    ("Brindlemere Capital", 2),
    ("Calderwell Advisors", 1),
]

#: Locations that are all recognised, so that a case about a title is not also
#: a case about a place. The geography block gets its own cases below.
PLACES = ["New York, NY", "NY-New York", "Boston, MA",
          "Remote - United States", "Chicago, IL"]

#: A description with no vocabulary in it: no timing phrase, no experience bar,
#: no graduation window, no advanced degree. Long enough to count as hydrated
#: (the gate caps anything shorter), so that the cases carrying it exercise the
#: scoring path that trusts a posting, and the empty ones exercise the cap.
FILLER = (
    "This role sits with the investment team and supports the written record "
    "that goes to the committee. The work is measured, documented and reviewed "
    "by the people who rely on it. Notes are circulated once a week and filed "
    "with the rest of the record, and questions are welcome at any point. "
)

#: `\\w*` is a stem, and the corpus should read like job titles rather than like
#: regular expressions: "software developer", not "software develop". The
#: expansion is checked against the pattern it came from before it is written,
#: so a wrong guess here is a build error and not a silent hole in the corpus.
SUFFIX = {"recruit": "er", "recepti": "onist", "engineer": "ing",
          "develop": "er", "bank": "ing", "econometric": "s",
          "research": "", "trad": "ing", "graduat": "ing"}

#: Tokens a title-caser would otherwise mangle into "Nyc" or "M&a".
ACRONYMS = {"ny", "nyc", "vp", "md", "hr", "swe", "sre", "qa", "ml", "asic",
            "fpga", "ios", "va", "dc", "m&a", "mba", "d.c"}


# ------------------------------------------------- one example per pattern
#
# Generating a string that matches a regular expression is, in general, a
# project. These are not general: a list of alternatives, a literal, `\s+`
# between two words, an optional group, a lookaround to dodge. So this walks the
# pattern once and takes the plainest reading of it — the first alternative, one
# copy of anything optional, nothing at all for a lookaround — and the caller
# checks the answer against the pattern before trusting it.


class Unsupported(ValueError):
    """A pattern this walker cannot read. Add a case for it by hand."""


def sample(pattern: str) -> str:
    """One string the pattern matches, built from the pattern itself."""
    text, position = _alternation(pattern, 0)
    if position != len(pattern):
        raise Unsupported(f"{pattern!r}: stopped reading at {position}")
    return re.sub(r"\s{2,}", " ", text).strip()


def _alternation(pattern: str, i: int) -> tuple[str, int]:
    """`a|b|c` → whatever `a` gives. The rest is read and thrown away."""
    text, i = _concat(pattern, i)
    while i < len(pattern) and pattern[i] == "|":
        _, i = _concat(pattern, i + 1)
    return text, i


def _concat(pattern: str, i: int) -> tuple[str, int]:
    out: list[str] = []
    while i < len(pattern) and pattern[i] not in "|)":
        piece, i = _piece(pattern, i, "".join(out))
        out.append(piece)
    return "".join(out), i


def _piece(pattern: str, i: int, so_far: str) -> tuple[str, int]:
    atom, i, kind = _atom(pattern, i)
    copies, i = _quantifier(pattern, i)
    if kind == "word" and copies is not None:
        # `\w*` after a stem: "recruit" wants "er", "engineer" wants "ing".
        stem = re.split(r"[^A-Za-z]", so_far.strip())[-1].lower()
        return SUFFIX.get(stem, "" if copies == 0 else "s"), i
    if copies is None:
        return atom, i
    if copies == 0 and atom == " ":
        # `\s*` between two words is still a gap; a title without it reads as a
        # typo, and one space matches just as well as none.
        return " ", i
    return atom * copies, i


def _quantifier(pattern: str, i: int) -> tuple[int | None, int]:
    """How many copies of the atom to write, or None when it is not quantified."""
    if i >= len(pattern):
        return None, i
    if pattern[i] in "?+":
        return 1, i + 1
    if pattern[i] == "*":
        return 0, i + 1
    if pattern[i] == "{":
        end = pattern.index("}", i)
        return max(int(pattern[i + 1:end].split(",")[0] or 0), 1), end + 1
    return None, i


def _atom(pattern: str, i: int) -> tuple[str, int, str]:
    char = pattern[i]
    if char == "(":
        if pattern.startswith("(?", i) and pattern[i + 2] in "=!<":
            return "", _skip_group(pattern, i), "look"   # a lookaround writes nothing
        start = i + 3 if pattern.startswith("(?:", i) else i + 1
        text, j = _alternation(pattern, start)
        return text, j + 1, "group"
    if char == "[":
        return _character_class(pattern, i)
    if char == "\\":
        return _escape(pattern[i + 1]), i + 2, "word" if pattern[i + 1] in "wW" else "escape"
    if char == ".":
        return "x", i + 1, "any"
    return char, i + 1, "literal"


def _skip_group(pattern: str, i: int) -> int:
    depth = 0
    while i < len(pattern):
        if pattern[i] == "\\":
            i += 2
            continue
        if pattern[i] == "(":
            depth += 1
        elif pattern[i] == ")":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    raise Unsupported(f"{pattern!r}: unbalanced group")


def _character_class(pattern: str, i: int) -> tuple[str, int, str]:
    end = pattern.index("]", i)
    body = pattern[i + 1:end]
    if body.startswith("^"):
        raise Unsupported(f"{pattern!r}: a negated class has no plain reading")
    members = re.findall(r"\\.|.", body)
    # A literal member first: `[\s-]` is how a board writes "full-stack", and
    # the hyphen reads better than the space `\s` would give.
    literal = [m for m in members if not m.startswith("\\")]
    if literal:
        return literal[0], end + 1, "class"
    return _escape(members[0][1]), end + 1, "class"


def _escape(char: str) -> str:
    return {"s": " ", "w": "a", "d": "0", "b": "", "B": ""}.get(char, char)


def phrase(pattern: str) -> str:
    """The sample, written the way a job board would write it."""
    words = sample(pattern).split(" ")
    return " ".join(w.upper() if w.lower() in ACRONYMS else _capitalised(w)
                    for w in words)


def _capitalised(word: str) -> str:
    """Capitalise each run of letters: "d.c" → "D.C", "full-stack" → "Full-Stack"."""
    return re.sub(r"[A-Za-z]+", lambda m: m.group(0).capitalize(), word)


# ------------------------------------------------------------ the entries
#
# What the configuration configures, as a flat list. The test imports this to
# assert the corpus covers all of it, so this is the one definition of "every
# entry" and the corpus and the test cannot drift apart on what that means.


def configured(raw: dict | None = None) -> list[tuple[str, str, int | None]]:
    """Every pattern in the shipped vocabulary, as (block, pattern, weight)."""
    raw = raw if raw is not None else yaml.safe_load(search.DEFAULTS.read_text())
    out: list[tuple[str, str, int | None]] = []
    for block in ("rejects", "class_scoped"):
        for name, patterns in (raw.get(block) or {}).items():
            out += [(f"{block}.{name}", pattern, None) for pattern in patterns]
    for key, entry in (raw.get("geography") or {}).items():
        out += [(f"geography.{key}", pattern, entry["weight"])
                for pattern in entry["patterns"]]
    out += [("non_us", pattern, None) for pattern in raw.get("non_us") or []]
    for block in ("role_fit", "timing", "title_timing"):
        out += [(block, pattern, weight) for pattern, weight in raw.get(block) or []]
    return out


# ------------------------------------------------------------- near-misses
#
# One title per entry proves the entry fires. It does not prove the entry stops
# firing where it should, and that is where a transcription bug hides: a dropped
# lookbehind rejects every rising senior, a dropped boundary reads "Basic
# Materials" as an ASIC job and "Leadership Development" as a lead. Each row
# below is a string the named entry must NOT match. The pattern is written out
# in full so that editing it in the YAML fails this file rather than quietly
# unhooking the case from the entry it was written for.

NEAR_MISSES: list[tuple[str, str, str]] = [
    # Lookarounds, which exist precisely to let these through.
    ("rejects.seniority", r'(?<!rising\s)senior(?!\s+year)',
     "Rising Senior Summer Analyst Programme"),
    ("rejects.seniority", r'(?<!rising\s)senior(?!\s+year)',
     "Senior Year Placement, Markets"),
    ("rejects.off_function", r'sales(?!\s*(?:and|&)\s*trading)',
     "Global Markets (Sales and Trading) Summer Analyst Programme"),
    ("rejects.off_function", r'sales(?!\s*(?:and|&)\s*trading)',
     "Sales & Trading Summer Analyst, 2027"),
    # This one is a near-miss for the class-year rule and a reject anyway: the
    # seniority lookbehind excuses "rising senior" and not "or senior", so the
    # gate refuses a title the timing block pays 12 for. Frozen as it behaves,
    # not as it was meant to; the old corpus of real postings never said so,
    # because not one of its 826 titles used the word.
    ("class_scoped.junior", r'rising\s+junior(?!\s+or)',
     "Rising Junior or Senior Investment Intern"),
    ("class_scoped.senior", r'rising\s+senior(?!\s+or)',
     "Rising Senior or Junior Summer Analyst"),
    # Word boundaries. Every one of these is a real title that a gate without
    # boundaries throws away.
    ("rejects.seniority", 'lead', "Leadership Development Analyst Programme"),
    ("rejects.seniority", 'partner', "Limited Partnerships Analyst"),
    ("rejects.seniority", 'staff', "Staffing Levels Analyst, Operations"),
    ("rejects.seniority", 'director', "Directory Services Analyst"),
    ("rejects.seniority", r'\bmd\b', "Analyst, MDM Reference Data"),
    ("rejects.off_function", r'\bhr\b', "HRIS Reporting Analyst"),
    ("rejects.too_technical", r'\basic\b', "Basic Materials Equity Research"),
    ("rejects.too_technical", 'developers?', "Developing Markets Research Analyst"),
    ("rejects.too_technical", r'\bios\b', "Biosciences Coverage Analyst"),
    ("class_scoped.freshman", r'first[\s-]?year\s+(student|intern)',
     "First Year Review Analyst"),
    ("role_fit", r'\banalyst\b', "Analytics Placement, Markets"),
    ("role_fit", r'\bintern(ship)?\b', "Internal Audit Placement"),
    ("role_fit", r'\btrader\b', "Traded Products Control Placement"),
    ("title_timing", r'\bclass\s+of\b', "Multi-Asset Class Placement"),
    ("title_timing", r'\b20(26|27)\b', "Research Analyst, 2029 Programme"),
    ("timing", r'part[\s-]?time', "Partial Coverage Research Analyst"),
]

#: The same, for the blocks that read a location rather than a title.
NEAR_MISS_PLACES: list[tuple[str, str, str]] = [
    ("geography.primary", r'\bny\b', "Sunnyvale, CA"),
    ("geography.home", r'your\s+home\s+city', "Your Home Cityscape, NY"),
    ("non_us", 'china', "Chinatown, New York, NY"),
    ("non_us", 'india', "Indianapolis, IN"),
]


# ------------------------------------------------------------- the algorithm
#
# score.py keeps the rules that are not one person's vocabulary: an experience
# bar, a credential bar, the eligibility window a campus programme states in its
# own words, the cap on a posting whose description has not been fetched. The
# YAML says nothing about them, so nothing above generates a case for them, and
# a refactor could quietly drop one. These are those cases, by hand.

#: A description that reads unmistakably as one track, for the bonus score.py
#: pays when the classifier is confident. Invented, like everything else here.
BANKING_BODY = (
    "The analyst supports deal execution across mergers and acquisitions: "
    "comparable company analysis, discounted cash flow work, and the pitchbook "
    "that goes with it. Recent work includes a leveraged buyout and a capital "
    "raise for a coverage group client. "
)

DEGREE_BODY = FILLER + "A master's degree is required for this position."
EXPERIENCE_BODY = FILLER + "Candidates need 5+ years of relevant experience."
WINDOW_MISSES = FILLER + "Expected graduation date of December 2027 - June 2028."
WINDOW_FITS = FILLER + "Graduating between December 2026 and June 2027."

ALGORITHM: list[dict] = [
    # A graduate programme in the title, whatever the body says.
    dict(title="Quantitative Analyst, Ph.D. Intern", location="New York, NY"),
    dict(title="MBA Summer Associate, Investment Banking", location="New York, NY"),
    # …and the opposite: pre-doctoral work is built for undergraduates.
    dict(title="Pre-Doctoral Research Assistant, Economics", location="New York, NY"),
    # The two bars in the body.
    dict(title="Research Analyst", location="New York, NY", body=EXPERIENCE_BODY),
    dict(title="Research Analyst", location="New York, NY", body=DEGREE_BODY),
    # The eligibility window a summer programme states, on both sides of it.
    dict(title="2027 Markets Summer Analyst Programme", location="New York, NY",
         body=WINDOW_MISSES),
    dict(title="2027 Markets Full-Time Analyst Programme", location="New York, NY",
         body=WINDOW_FITS),
    # A rank that is senior at this firm and nowhere else.
    dict(title="Quantitative Research - Markets - Associate", location="New York, NY",
         senior_grades=("associate",)),
    dict(title="Quantitative Research - Markets - Associate", location="New York, NY"),
    # Places the configuration says nothing about: a state name is enough, a
    # foreign region is not, a bare city is neither.
    dict(title="Research Analyst", location="Boise, Idaho"),
    dict(title="Research Analyst", location="Kyiv, Ukraine"),
    dict(title="Research Analyst", location="Chantilly"),
    dict(title="Research Analyst", location=""),
    # The priority bonus, including a firm that is on no list at all.
    dict(title="Summer Analyst Programme", location="New York, NY", priority=1),
    dict(title="Summer Analyst Programme", location="New York, NY", priority=2),
    dict(title="Summer Analyst Programme", location="New York, NY", priority=3),
    dict(title="Summer Analyst Programme", location="New York, NY", priority=0),
    # A description the classifier is sure about, and the same title without it.
    dict(title="Analyst Programme", location="New York, NY", body=BANKING_BODY),
    dict(title="Analyst Programme", location="New York, NY", body=FILLER),
    # The firm's declared track, matched and unmatched.
    dict(title="Quantitative Research Analyst", location="New York, NY",
         body=FILLER, tracks=("quant",)),
    dict(title="Quantitative Research Analyst", location="New York, NY",
         body=FILLER, tracks=("banking",)),
    # The cap, on a posting good enough to feel it: the same title with and
    # without a description behind it. Unhydrated it cannot score above the
    # pursue bar plus nine, however well it reads.
    dict(title="Quantitative Research Summer Analyst Programme, Summer 2027",
         location="New York, NY", priority=1),
    dict(title="Quantitative Research Summer Analyst Programme, Summer 2027",
         location="New York, NY", priority=1, body=FILLER),
    # A standing the posting is not aimed at, and the same posting for the
    # student it is aimed at.
    dict(title="Sophomore Summer Analyst Programme", location="New York, NY"),
    dict(title="Sophomore Summer Analyst Programme", location="New York, NY",
         standing="sophomore"),
]


# ----------------------------------------------------------- writing it out


def case(entry: tuple[str, str], kind: str, title: str, location: str,
         index: int, *, body: str = "", employer: str | None = None,
         priority: int | None = None, standing: str | None = None,
         senior_grades: tuple[str, ...] = (), tracks: tuple[str, ...] = ()) -> dict:
    """One scored case, carrying the entry it was built to exercise.

    `kind` is "entry" when the named pattern is meant to match what this case
    holds, "near-miss" when it is meant not to, and "algorithm" for a rule that
    lives in score.py and has no configured pattern to name.
    """
    name, firm_priority = EMPLOYERS[index % len(EMPLOYERS)]
    posting = RawPosting(
        employer=employer or name, title=title, url="", source="synthetic",
        location=location, description=body,
        employer_priority=firm_priority if priority is None else priority,
        employer_senior_grades=senior_grades, employer_tracks=tracks)
    verdict = score(posting, PREFERENCES, standing, config=SHIPPED)
    row = {
        "entry": list(entry), "kind": kind,
        "employer": posting.employer, "title": title, "location": location,
        "priority": posting.employer_priority, "body": body,
        "value": verdict.value, "verdict": verdict.verdict.value,
        "rejected_by": verdict.rejected_by, "reasons": verdict.reasons,
    }
    if standing:
        row["standing"] = standing
    if senior_grades:
        row["senior_grades"] = list(senior_grades)
    if tracks:
        row["tracks"] = list(tracks)
    return row


#: The blocks whose entries the gate wraps in non-alphanumeric boundaries. The
#: weighted blocks — role_fit, timing, title_timing — are used as written. See
#: the header of search.defaults.yaml, and `_any` in search.py.
BOUNDED = ("rejects", "class_scoped", "geography", "non_us")


def compiled(path: str, pattern: str) -> re.Pattern:
    """One entry on its own, compiled the way its own block is compiled.

    The corpus says of each case whether the entry it names matches it, and the
    test checks that claim. Checking it with the wrong boundaries would make the
    claim about this function rather than about the gate.
    """
    if path.split(".")[0] in BOUNDED:
        return re.compile(rf"(?<![A-Za-z0-9]){pattern}(?![A-Za-z0-9])", re.I)
    return re.compile(pattern, re.I)


def reads(row: dict) -> str:
    """Everything the gate reads of one case: title, location, description."""
    return f"{row['title']}\n{row['location']}\n{row['body']}"


def _must(condition: bool, complaint: str) -> None:
    if not condition:
        raise SystemExit(f"synthesize_corpus: {complaint}")


def _refused_by(title: str) -> str | None:
    """Which reject block a title lands in, by the order the gate runs them.

    Usually the block the case was written for. Not always: the reject blocks
    run in the order the configuration lists them and the first match ends it,
    so a title built for off_function's `account\\s+executive` is refused as
    senior, because "executive" is a rank and seniority runs first. The entry is
    still exercised — its pattern matches the title — but the verdict belongs to
    the earlier block, and a corpus that insisted otherwise would be asserting
    something the gate does not do.
    """
    for name, compiled in SHIPPED.rejects.items():
        if compiled.search(title):
            return _REJECT_LABEL.get(name, name)
    return None


def build() -> list[dict]:
    raw = yaml.safe_load(search.DEFAULTS.read_text())
    cases: list[dict] = []
    frames = ["{}, Global Markets", "2027 {} Programme", "{} - Americas"]

    for index, (path, pattern, weight) in enumerate(configured(raw)):
        block = path.split(".")[0]
        body = FILLER if index % 3 == 2 else ""
        text = phrase(pattern)

        if block == "rejects":
            title = frames[index % len(frames)].format(text)
            row = case((path, pattern), "entry", title, PLACES[index % len(PLACES)], index)
            _must(bool(compiled(path, pattern).search(title)),
                  f"{title!r} does not match {pattern!r}")
            _must(row["rejected_by"] == _refused_by(title),
                  f"{title!r} was meant to be refused by {_refused_by(title)}, "
                  f"and was {row['rejected_by']}")

        elif block == "class_scoped":
            year = path.split(".")[1]
            title = f"{text} Summer Analyst Programme"
            row = case((path, pattern), "entry", title, PLACES[index % len(PLACES)], index)
            _must(bool(compiled(path, pattern).search(title)),
                  f"{title!r} does not match {pattern!r}")
            _must((row["rejected_by"] == "class year") is (year != CLASS_STANDING),
                  f"{title!r} is scoped to {year}; the reader is a "
                  f"{CLASS_STANDING} and it was {row['rejected_by']}")

        elif block == "geography":
            key = path.split(".")[1]
            in_title = bool(raw["geography"][key].get("match_title"))
            title = f"Research Analyst ({text})" if in_title else "Research Analyst"
            location = "" if in_title else text
            row = case((path, pattern), "entry", title, location, index, body=body)
            _must(f"{raw['geography'][key].get('label', key)} +{weight}"
                  in row["reasons"],
                  f"{location or title!r} did not score as {path}: {row['reasons']}")

        elif block == "non_us":
            row = case((path, pattern), "entry", "Research Analyst", text, index, body=body)
            _must(row["rejected_by"] == "geography",
                  f"{text!r} was meant to be somewhere else, and was "
                  f"{row['rejected_by']}")

        elif block == "role_fit":
            row = case((path, pattern), "entry", text, PLACES[index % len(PLACES)],
                       index, body=body)
            _must(f"role fit +{weight}" in row["reasons"],
                  f"{text!r} did not score role fit +{weight}: {row['reasons']}")

        elif block == "timing":
            # Read against the title and the first 2000 characters of the body;
            # this is the body half, so the title stays neutral.
            row = case((path, pattern), "entry", "Research Analyst",
                       PLACES[index % len(PLACES)], index, body=FILLER + text)
            _must(f"timing +{weight}" in row["reasons"],
                  f"a body saying {text!r} did not score timing +{weight}: "
                  f"{row['reasons']}")

        else:                                            # title_timing
            row = case((path, pattern), "entry", f"Research Analyst, {text}",
                       PLACES[index % len(PLACES)], index, body=body)
            _must(f"timing +{weight}" in row["reasons"],
                  f"a title saying {text!r} did not score timing +{weight}: "
                  f"{row['reasons']}")

        cases.append(row)

    known = {(path, pattern) for path, pattern, _ in configured(raw)}
    misses = ([(path, pattern, title, "") for path, pattern, title in NEAR_MISSES]
              + [(path, pattern, "Research Analyst", location)
                 for path, pattern, location in NEAR_MISS_PLACES])
    for index, (path, pattern, title, location) in enumerate(misses):
        _must((path, pattern) in known,
              f"the near-miss {title!r} names {path} {pattern!r}, which is no "
              "longer in search.defaults.yaml — rewrite it against what is there")
        row = case((path, pattern), "near-miss", title,
                   location or PLACES[index % len(PLACES)], index)
        _must(not compiled(path, pattern).search(reads(row)),
              f"{title!r} / {location!r} was meant to be a near-miss for "
              f"{pattern!r}, and matches it")
        cases.append(row)

    for index, row in enumerate(ALGORITHM):
        cases.append(case(("algorithm", ""), "algorithm", row["title"],
                          row["location"], index, body=row.get("body", ""),
                          priority=row.get("priority"),
                          standing=row.get("standing"),
                          senior_grades=row.get("senior_grades", ()),
                          tracks=row.get("tracks", ())))
    return cases


def main() -> None:
    cases = build()
    covered = {tuple(row["entry"]) for row in cases if row["kind"] == "entry"}
    missing = [f"{path} {pattern!r}" for path, pattern, _ in configured()
               if (path, pattern) not in covered]
    _must(not missing, f"{len(missing)} entries have no case: {missing[:5]}")

    head = {
        "note": ("Synthesised from src/apply/search.defaults.yaml by "
                 "tools/synthesize_corpus.py. Every firm here is invented and "
                 "every title is assembled from a configured pattern; nothing "
                 "in this file comes from a real posting or a real pipeline."),
        "graduation": list(GRADUATION), "class_standing": CLASS_STANDING,
        "cases": cases,
    }
    OUT.write_text(json.dumps(head, indent=1) + "\n")
    counts = {kind: sum(1 for row in cases if row["kind"] == kind)
              for kind in ("entry", "near-miss", "algorithm")}
    print(f"{len(cases)} cases -> {OUT} ({OUT.stat().st_size // 1024} KB)")
    print("  " + ", ".join(f"{count} {kind}" for kind, count in counts.items()))
    print(f"  covering all {len(configured())} entries in {search.DEFAULTS.name}")


if __name__ == "__main__":
    main()
