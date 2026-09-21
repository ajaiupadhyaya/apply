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
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum

from .classify import classify
from .sources.base import RawPosting


class Verdict(str, Enum):
    PURSUE = "pursue"     # write the letter
    MAYBE = "maybe"       # borderline; worth a cheap model's opinion
    REJECT = "reject"     # never reaches a document


def _any(patterns: list[str]) -> re.Pattern:
    return re.compile("|".join(rf"(?<![A-Za-z0-9]){p}(?![A-Za-z0-9])" for p in patterns), re.I)


# ----------------------------------------------------------- hard rejects

#: Titles that are not open to someone graduating in 2027, whatever else they say.
SENIORITY = _any([
    r"senior", r"sr\.?", r"vice\s+president", r"\bvp\b", r"director", r"principal",
    r"staff", r"lead", r"head\s+of", r"chief", r"executive", r"managing\s+director",
    r"\bmd\b", r"partner", r"manager", r"supervisor", r"president",
])

#: Functions that are not what this person does, however senior.
OFF_FUNCTION = _any([
    r"sales", r"account\s+executive", r"recruit\w*", r"talent", r"marketing",
    r"human\s+resources", r"\bhr\b", r"facilities", r"custodian", r"janitor",
    r"nurse", r"physician", r"paralegal", r"attorney", r"counsel",
    r"executive\s+assistant", r"receptionist", r"copywriter", r"designer",
    r"video", r"social\s+media", r"community\s+manager", r"support\s+specialist",
    # Found by a live pass: "Workplace Services Rotational Coordinator" scored 61
    # on the strength of the word "rotational".
    r"coordinator", r"administrator", r"office\s+manager", r"workplace\s+services",
    r"recruiter", r"chef", r"barista", r"events?", r"recepti\w*",
])

#: The line inside technology. Analysis of a business: yes. Building the product: no.
TOO_TECHNICAL = _any([
    r"software\s+engineer", r"\bswe\b", r"backend", r"back-end", r"frontend",
    r"front-end", r"full[\s-]?stack", r"mobile\s+engineer", r"\bios\b", r"android",
    r"devops", r"\bsre\b", r"site\s+reliability", r"security\s+engineer",
    r"infrastructure\s+engineer", r"platform\s+engineer", r"systems\s+engineer",
    r"network\s+engineer", r"firmware", r"embedded", r"\bqa\b",
    r"quality\s+assurance", r"data\s+engineer", r"machine\s+learning\s+engineer",
    r"\bml\s+engineer\b", r"solutions\s+architect", r"web\s+developer",
    # Found by a live pass: "Hardware Engineer (FPGA/ASIC)" scored 59.
    r"hardware\s+engineer", r"\bfpga\b", r"\basic\b", r"electrical\s+engineer",
    r"\bsysadmin\b", r"database\s+administrator", r"compiler", r"kernel",
])

#: Experience and credential bars a 2027 undergraduate cannot clear.
YEARS = re.compile(r"(\d+)\s*\+?\s*(?:-\s*\d+\s*)?years?(?:\s+of)?\s+(?:relevant\s+|professional\s+|work\s+)?experience", re.I)
ADVANCED_DEGREE = re.compile(
    r"(ph\.?d|doctorate|mba|master'?s|graduate\s+degree|advanced\s+degree)[^.]{0,40}"
    r"(required|is\s+required|must\s+have|mandatory)", re.I)

#: Places. NYC is the stated goal, so it is the heaviest single signal here.
NYC = _any([r"new\s+york", r"\bnyc\b", r"manhattan", r"\bny\b", r"hudson\s+yards"])
HOME = _any([r"richmond", r"charlottesville", r"virginia", r"\bva\b",
             r"washington,?\s*d\.?c", r"arlington", r"alexandria", r"mclean", r"reston"])
HUB = _any([r"boston", r"chicago", r"san\s+francisco", r"stamford", r"greenwich",
            r"jersey\s+city", r"philadelphia", r"charlotte", r"atlanta", r"dallas",
            r"houston", r"los\s+angeles", r"miami", r"austin", r"seattle", r"denver"])
REMOTE = _any([r"remote", r"work\s+from\s+home", r"virtual", r"anywhere"])

#: A location string with none of the above and one of these is somewhere else.
NON_US = _any([
    r"london", r"hong\s+kong", r"singapore", r"tokyo", r"shanghai", r"mumbai",
    r"bengaluru", r"bangalore", r"gurgaon", r"hyderabad", r"amsterdam", r"dublin",
    r"paris", r"frankfurt", r"munich", r"zurich", r"geneva", r"milan", r"madrid",
    r"toronto", r"montreal", r"vancouver", r"sydney", r"melbourne", r"sao\s+paulo",
    r"mexico\s+city", r"budapest", r"warsaw", r"tel\s+aviv", r"dubai", r"seoul",
    r"taipei", r"manila", r"kuala\s+lumpur", r"bucharest", r"edinburgh", r"glasgow",
    r"united\s+kingdom", r"india", r"china", r"japan", r"germany", r"france",
    r"netherlands", r"ireland", r"switzerland", r"canada", r"australia", r"brazil",
])


# -------------------------------------------------------- positive signals

#: Title patterns, best match wins. The ceiling is 25 so that a bullseye posting
#: — right role, right timing, right city, target firm — lands near 90 and clears
#: the pursue bar with room to spare. Calibrated against the two seed postings.
ROLE_FIT = [
    # Loose between "quantitative" and the noun: "Quantitative Finance
    # Researcher" is the same job as "Quantitative Researcher".
    (r"quantitative[\s\w]{0,18}(research\w*|analyst|trader|trading)", 25),
    (r"quantitative\s+(research\w*|trad\w*|analyst)", 25),
    # Graduate programmes are what the banks call an analyst programme, and
    # they are exactly the thing worth catching.
    (r"graduate\s+(program|programme|scheme|analyst)", 23),
    (r"sales\s+and\s+trading", 22),
    (r"analyst\s+program", 22),
    (r"summer\s+analyst", 22),
    (r"investment\s+bank\w*\s+(analyst|associate|intern)", 22),
    (r"investment\s+(analyst|associate|intern)", 20),
    (r"equity\s+research", 20),
    (r"research\s+(analyst|associate|assistant)", 19),
    (r"econometric\w*", 19),
    (r"risk\s+(analyst|management|intern)", 18),
    (r"portfolio\s+(analyst|management|operations)", 18),
    (r"financial\s+analyst", 18),
    (r"credit\s+analyst", 18),
    (r"economist", 17),
    (r"investment\s+management", 19),
    (r"private\s+(equity|credit|bank\w*)", 19),
    (r"\bm&a\b", 19),
    (r"corporate\s+bank\w*", 18),
    (r"capital\s+markets", 17),
    (r"asset\s+management", 17),
    (r"wealth\s+management", 14),
    (r"treasury", 14),
    (r"actuarial", 13),
    (r"trading\s+(analyst|assistant|intern)", 17),
    (r"\btrader\b", 16),
    (r"corporate\s+development", 16),
    (r"strategy\s+(analyst|associate|intern)", 14),
    (r"business\s+analyst", 14),
    (r"data\s+analyst", 13),
    (r"financial\s+planning", 13),
    (r"\banalyst\b", 12),
    (r"\bassociate\b", 9),
    (r"\bintern(ship)?\b", 8),
]

#: When the role is aimed at someone in this person's position. Best match wins.
TIMING = [
    (r"pre[\s-]?doctoral|predoc", 20),
    (r"summer\s+20(26|27)", 18),
    (r"20(26|27)\s+(summer|full[\s-]?time|analyst)", 18),
    (r"class\s+of\s+20(27|28)", 18),
    (r"full[\s-]?time\s+analyst", 17),
    (r"campus|university\s+(hire|program|recruit)|early\s+career", 16),
    (r"new\s+grad(uate)?", 16),
    (r"rising\s+(junior|senior)", 16),
    (r"research\s+assistant", 15),
    (r"rotational\s+program", 14),
    (r"undergraduate", 12),
    (r"graduating\s+(student|in)", 12),
    (r"\bjunior\s+or\s+senior\b", 12),
    (r"part[\s-]?time", 8),
    (r"\bintern(ship)?\b", 8),
]


#: Checked against the title alone. A year in a job title is a campus signal;
#: the same year buried in a description usually is not.
TITLE_TIMING = [
    (r"\b20(26|27)\b", 14),
    (r"\bclass\s+of\b", 14),
]


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


DEFAULT_THRESHOLDS = {"pursue": 70, "maybe": 45}


def score(posting: RawPosting, preferences: dict | None = None) -> Score:
    """Relevance only. Urgency is the digest's job, not this function's."""
    preferences = preferences or {}
    thresholds = {**DEFAULT_THRESHOLDS, **(preferences.get("thresholds") or {})}
    title = posting.title or ""
    location = posting.location or ""
    body = posting.description or ""
    reasons: list[str] = []

    def reject(why: str, by: str) -> Score:
        return Score(0, Verdict.REJECT, [why], rejected_by=by)

    # --- hard gates, cheapest first -------------------------------------
    if SENIORITY.search(title):
        return reject(f"title is senior: {SENIORITY.search(title).group(0)!r}", "seniority")
    if OFF_FUNCTION.search(title):
        return reject(f"off-function: {OFF_FUNCTION.search(title).group(0)!r}", "function")
    if TOO_TECHNICAL.search(title):
        return reject(f"engineering role: {TOO_TECHNICAL.search(title).group(0)!r}", "technical")

    remote = bool(REMOTE.search(location) or REMOTE.search(title))
    in_nyc = bool(NYC.search(location))
    if not (in_nyc or remote or HOME.search(location) or HUB.search(location)):
        if NON_US.search(location):
            return reject(f"outside the US: {location!r}", "geography")
        if location and not re.search(r"united\s+states|,\s*[A-Z]{2}\b|\busa\b", location, re.I):
            return reject(f"location not recognised as US: {location!r}", "geography")

    if body:
        years = YEARS.search(body)
        if years and int(years.group(1)) >= 3:
            return reject(f"asks for {years.group(1)}+ years of experience", "experience")
        degree = ADVANCED_DEGREE.search(body)
        if degree:
            return reject(f"requires an advanced degree: {degree.group(0)[:48]!r}", "degree")

    # --- positive signal -------------------------------------------------
    value = 0
    best_role = 0
    for pattern, weight in ROLE_FIT:
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
    for pattern, weight in TIMING:
        if re.search(pattern, haystack, re.I):
            timing_hit = max(timing_hit, weight)
    for pattern, weight in TITLE_TIMING:
        if re.search(pattern, title, re.I):
            timing_hit = max(timing_hit, weight)
    if timing_hit:
        value += timing_hit
        reasons.append(f"timing +{timing_hit}")

    # New York is the stated goal, so it is the single heaviest signal here.
    if in_nyc:
        value += 25
        reasons.append("New York +25")
    elif HOME.search(location):
        value += 15
        reasons.append("local to Richmond +15")
    elif remote:
        value += 10
        reasons.append("remote +10")
    elif HUB.search(location):
        value += 6
        reasons.append("US finance hub +6")

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
