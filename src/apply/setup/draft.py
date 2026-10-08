"""From a resume and a few answers to a working configuration.

One request drafts everything; a deterministic pass then removes whatever the
user's own documents do not support, and the user approves each section before
a file is written. The model proposes; the documents and the user decide.

The pass checks what can be checked mechanically: names, organisations, titles,
schools, skills, links, dates and every figure. Prose with no figure in it
cannot be verified deterministically; it is left to the user, who approves
each section before it is written.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Literal

from pydantic import BaseModel, Field

from ..profile import ASK, _digit_tokens

SECTIONS = ("identity", "experience", "projects", "skills", "writing", "search")
PURPOSE = "setup"
#: The draft is one long request; the everyday $0.50 per-call ceiling is for
#: letters. Setup runs once, so it gets its own, stated here.
SETUP_PER_CALL_USD = 2.00


class Identity(BaseModel):
    legal_first: str
    legal_last: str
    preferred_name: str | None = None
    email: str
    city: str = ""
    state: str = ""


class Education(BaseModel):
    institution: str
    degree: str = ""
    major: str = ""
    start: str = Field("ASK", description="YYYY-MM, or ASK if the documents do not say")
    current: bool = False


class Experience(BaseModel):
    org: str
    title: str
    start: str = Field(description="YYYY-MM or ASK")
    end: str = Field(description="YYYY-MM, 'present', or ASK")
    location: str = ""
    bullets: list[str]
    detail: list[str] = Field(default_factory=list, description="longer source notes on the role, from the documents")
    tags: list[str] = Field(default_factory=list)


class Project(BaseModel):
    key: str = Field(description="short snake_case id")
    name: str
    url: str | None = None
    tracks: list[str]
    one_line: str
    three_line: str
    resume_line: str
    technical: str = ""
    stack: list[str] = Field(default_factory=list)


class SkillGroup(BaseModel):
    group: str
    items: list[str]


class Keyword(BaseModel):
    phrase: str
    weight: int = Field(ge=1, le=5)


class TrackDraft(BaseModel):
    name: str = Field(min_length=1, description="lowercase, one word: 'swe', 'consulting', 'quant'")
    keywords: list[Keyword]
    resume: Literal["projects_first", "experience_first"]
    code_link: bool
    proof_asset: str = Field(description="default subject of letter paragraph 2 on this track")


class Weighted(BaseModel):
    match: str
    weight: int


class Place(BaseModel):
    label: str
    weight: int
    match: list[str]
    title: bool = False


class EmployerDraft(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    tracks: list[str]
    priority: int = Field(ge=1, le=3)


class Draft(BaseModel):
    identity: Identity
    education: list[Education]
    experience: list[Experience]
    projects: list[Project]
    skills: list[SkillGroup]
    voice: str
    letter_length: str
    letter_structure: str
    why_role: str
    avoid: list[str]
    tracks: list[TrackDraft] = Field(min_length=1)
    default_track: str
    roles: list[Weighted]
    timing: list[Weighted]
    title_timing: list[Weighted]
    locations: list[Place]
    reject_seniority: list[str]
    reject_functions: list[str]
    reject_technical: list[str]
    max_years_experience: int | None
    reject_advanced_degree: bool
    reject_graduate_programs: bool
    employers: list[EmployerDraft]


@dataclass
class Answers:
    roles: str
    job_types: list[str]
    locations: list[str]
    remote_ok: bool
    firms: list[str]
    avoid: str
    links: dict
    extra: str
    work_authorized: bool
    sponsorship_now: bool
    sponsorship_future: bool
    grad_expected: str
    student: bool
    availability_full_time: str | None
    availability_internship: str | None
    phone: str | None = None
    street_address: str | None = None
    gpa: str | None = None

    #: Never sent to the API, never written to a public file.
    PRIVATE = ("phone", "street_address", "gpa")

    def public(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k not in self.PRIVATE}


SYSTEM = """You configure APPLY, a local tool that finds job postings for one person and drafts
their cover letters. From their DOCUMENTS and ANSWERS, propose their profile and search criteria.

Hard rules:
- Use only facts present in the DOCUMENTS or ANSWERS. Never invent an employer, title, date,
  figure, skill, project or link. If a date is not stated, write ASK.
- Bullets and project lines restate the documents in tight, concrete language; they may shorten,
  never embellish. Keep every figure exactly as written.
- voice, letter_length, letter_structure, why_role and avoid are INSTRUCTIONS to a future letter
  writer about tone, structure and emphasis — never sentences to paste. letter_structure describes
  four body paragraphs and a closing: paragraph 2 carries one piece of work in operational detail.
- tracks: 1 to 4 kinds of role this person is applying for, each a one-word lowercase name, with
  8-20 weighted keyword phrases that appear in postings for that kind of role (5 decisive, 1 weak).
  projects_first for technical or portfolio-driven roles, experience_first otherwise. code_link
  only when the person has public code or work worth linking. Every project lists the tracks it
  supports; default_track is the most general one.
- roles are title phrases (weight 8-25, best fit highest); timing phrases mark postings aimed at
  this person's career stage (weight 8-20); locations are ordered most-wanted first (weight 25 for
  the top place, down to 6), with a remote entry (title: true) only if remote is OK. reject_* are
  words in a TITLE that make a posting wrong for this person: leave out of reject_seniority any
  level they qualify for, and leave reject_technical empty for a technical candidate.
  max_years_experience: the smallest required-experience figure they cannot meet (null if
  experienced). Plain phrases, not regular expressions.
- employers: only firms the person named, with common alternate spellings as aliases.
- Copy names (employers, schools, projects, skills, titles) exactly as the DOCUMENTS write them:
  no added suffixes, expansions or parentheticals.
Return the structured object only."""


def _without_private(sources: str, answers: Answers) -> str:
    """The documents with the private answers taken out, whatever the caller
    already did: a phone, a street address or a GPA never reaches the API."""
    from .extract import redact

    text = redact(sources, phone=answers.phone, address=answers.street_address)
    if answers.gpa and answers.gpa.strip():
        text = re.sub(rf"(?<![\d.]){re.escape(answers.gpa.strip())}(?!\.?\d)", "[gpa]", text)
    return text


def _user_message(sources: str, answers: Answers, note: str) -> str:
    sources = _without_private(sources, answers)
    text = (f"DOCUMENTS\n=========\n{sources}\n\n"
            f"ANSWERS\n=======\n{json.dumps(answers.public(), indent=1)}\n")
    if note:
        text += f"\nCORRECTION FROM THE USER (apply it)\n===================================\n{note}\n"
    return text


def request(sources: str, answers: Answers, note: str = "", *, budget=None) -> Draft:
    from .. import llm

    user = _user_message(sources, answers, note)
    model = llm.DEFAULT_MODEL
    if budget is not None:
        # Budget.caps is the ledger's own mutable dict: raise this one call's
        # ceiling for setup, never lower one the owner set higher.
        budget.caps["per_call_usd"] = max(budget.caps.get("per_call_usd", 0), SETUP_PER_CALL_USD)
        budget.check(llm.estimate(len(user) + len(SYSTEM), output_tokens=8000, model=model), PURPOSE)
    result, usage = llm.call(system=[{"type": "text", "text": SYSTEM}], user=user,
                             schema=Draft, model=model, effort="medium")
    if budget is not None:
        budget.record(usage, PURPOSE)
    return result


_YM = re.compile(r"^(\d{4})-(\d{2})$")


def _present(phrase: str, low: str) -> bool:
    """Whether a phrase appears in the lowercased corpus as whole words, so that
    "Meta" is not sourced by "metadata"."""
    from ..search import _pattern_for

    phrase = (phrase or "").strip().lower()
    if not phrase:
        return False
    return re.search(rf"(?<![a-z0-9]){_pattern_for(phrase)}(?![a-z0-9])", low) is not None


def ground(d: Draft, sources: str, answers: Answers, note: str = "") -> tuple[Draft, list[str]]:
    """Remove what the documents do not support. Deterministic: the model's
    output is a proposal, this is the check.

    The corpus is the documents and the user's correction note — a fact the
    user typed is sourced. The other answers are not: `firms` names employers
    the user wants, not ones they worked for, and the role blurb is a wish. Two
    exceptions: a link the user gave sources a URL, and the graduation and
    availability answers source a figure or a date. Names, titles, organisations,
    skills and figures are checked against it; prose without a figure in it
    cannot be, and is left to the user's approval of each section."""
    d = d.model_copy(deep=True)
    notes: list[str] = []
    corpus = sources + "\n" + (note or "")
    stated = " ".join(str(v) for v in (answers.grad_expected, answers.availability_full_time,
                                       answers.availability_internship) if v)
    allowed = _digit_tokens(corpus + "\n" + stated)
    years = set(re.findall(r"\b(?:19|20)\d{2}\b", corpus + "\n" + stated))
    low = corpus.lower()
    links = (low + "\n" + "\n".join(str(v) for v in (answers.links or {}).values())).lower()

    def unsourced(text: str) -> list[str]:
        return sorted(t for t in _digit_tokens(text or "") if t not in allowed)

    def date_ok(value: str, where: str) -> str:
        if value in (ASK, "present", "", None):
            return value
        m = _YM.match(value)
        if m and m.group(1) in years:
            return value
        notes.append(f"{where}: date {value!r} is not in your documents; set to ASK")
        return ASK

    def fact(value: str | None, where: str) -> str | None:
        """The value if the corpus names it, else ASK (blank stays blank)."""
        if value in (None, "", ASK) or _present(value, low):
            return value
        notes.append(f"{where}: {value!r} is not in your documents; set to ASK")
        return ASK

    ident = d.identity
    ident.legal_first = fact(ident.legal_first, "name")
    ident.legal_last = fact(ident.legal_last, "name")
    ident.email = fact(ident.email, "email")

    education = []
    for edu in d.education:
        if not _present(edu.institution, low):
            notes.append(f"dropped the school {edu.institution!r}: not named in your documents")
            continue
        edu.degree = fact(edu.degree, edu.institution)
        edu.major = fact(edu.major, edu.institution)
        edu.start = date_ok(edu.start, edu.institution)
        education.append(edu)
    d.education = education

    kept = []
    for e in d.experience:
        if not _present(e.org, low):
            notes.append(f"dropped the role at {e.org!r}: not named in your documents")
            continue
        e.title = fact(e.title, f"{e.org} title")
        e.start, e.end = date_ok(e.start, e.org), date_ok(e.end, e.org)
        for attr in ("bullets", "detail"):
            lines = []
            for line in getattr(e, attr):
                bad = unsourced(line)
                if bad:
                    notes.append(f"{e.org}: dropped a line — {', '.join(bad)} is not in your documents")
                else:
                    lines.append(line)
            setattr(e, attr, lines)
        kept.append(e)
    d.experience = kept

    def only_sourced(items: list[str], where: str) -> list[str]:
        out = []
        for item in items:
            if _present(item, low):
                out.append(item)
            else:
                notes.append(f"{where}: dropped {item!r} — not in your documents")
        return out

    projects = []
    for p in d.projects:
        if not _present(p.name, low):
            notes.append(f"dropped the project {p.name!r}: not named in your documents")
            continue
        for attr in ("one_line", "three_line", "resume_line", "technical"):
            bad = unsourced(getattr(p, attr))
            if bad:
                notes.append(f"{p.name}: cleared {attr} — {', '.join(bad)} is not in your documents")
                setattr(p, attr, "" if attr == "technical" else ASK)
        if p.url and p.url.lower().removeprefix("https://").removeprefix("http://") not in links:
            notes.append(f"{p.name}: removed the link — it is not in your documents or answers")
            p.url = None
        p.stack = only_sourced(p.stack, f"{p.name} stack")
        projects.append(p)
    d.projects = projects

    for group in d.skills:
        group.items = only_sourced(group.items, f"skills ({group.group})")
    return d, notes


def _rx(phrase: str) -> str:
    from ..search import _pattern_for
    return _pattern_for(phrase)


def _bounded(phrase: str) -> str:
    return rf"(?<![A-Za-z0-9]){_rx(phrase)}(?![A-Za-z0-9])"


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "place"


def _track(name: str) -> str:
    return (name or "").strip().lower()


def _without_lookaround(pattern: str) -> str:
    """A pattern with its (?<!…), (?<=…), (?!…) and (?=…) groups removed:
    '(?<!rising\\s)senior(?!\\s+year)' → 'senior'."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith(("(?<!", "(?<=", "(?!", "(?="), i):
            depth = 0
            while i < len(pattern):
                if pattern[i] == "\\":
                    i += 2
                    continue
                depth += {"(": 1, ")": -1}.get(pattern[i], 0)
                i += 1
                if depth == 0:
                    break
            continue
        out.append(pattern[i])
        if pattern[i] == "\\" and i + 1 < len(pattern):
            out.append(pattern[i + 1])
            i += 1
        i += 1
    return "".join(out)


def _rejects(phrases: list[str], defaults: list[str]) -> list[str]:
    """Drafted reject phrases as patterns. A phrase that is a default's base
    word gets the default's pattern, guards and all: the shipped 'senior' knows
    "Rising Senior Summer Analyst" is a student, and 'sales' knows "Sales and
    Trading" is a markets desk. A plain phrase would forget both."""
    bases = {_without_lookaround(p).lower(): p for p in defaults}
    out = []
    for phrase in phrases:
        rx = _rx(phrase)
        out.append(bases.get(rx.lower()) or bases.get(phrase.strip().lower()) or rx)
    return out


def to_files(d: Draft, answers: Answers) -> dict[str, dict]:
    import yaml

    from . import persona
    from ..search import DEFAULTS, country_of

    data = persona()
    tracks = {}
    for t in d.tracks:
        if _track(t.name):
            tracks.setdefault(_track(t.name), t)
    if not tracks:
        raise ValueError("the draft names no track; ask for it again")
    default = _track(d.default_track)
    if default not in tracks:
        default = next(iter(tracks))
    data["identity"] = {"legal_first": d.identity.legal_first, "legal_last": d.identity.legal_last,
                        "preferred_name": d.identity.preferred_name or d.identity.legal_first,
                        "email": d.identity.email,
                        "location": {"city": d.identity.city or ASK, "state": d.identity.state or ""}}
    data["links"] = dict(answers.links)
    education = [e.model_dump() for e in d.education] or [{"institution": ASK, "current": True}]
    current = next((e for e in education if e.get("current")), education[0])
    current["current"] = True
    current["grad_expected"] = answers.grad_expected
    data["education"] = education
    data["availability"] = {"full_time": answers.availability_full_time or ASK,
                            "internship": answers.availability_internship or ASK}
    data["authorization"] = {"us_work_authorized": answers.work_authorized,
                             "requires_sponsorship_now": answers.sponsorship_now,
                             "requires_sponsorship_future": answers.sponsorship_future,
                             "felony": False, "veteran": False}
    data["experience"] = [e.model_dump() for e in d.experience]
    data["projects"] = {p.key: {**{k: v for k, v in p.model_dump().items() if k != "key"},
                                "tracks": [t for t in dict.fromkeys(map(_track, p.tracks))
                                           if t in tracks] or [default]}
                        for p in d.projects}
    data["skills"] = {g.group: g.items for g in d.skills}
    data["essays"] = {k: None for k in (data.get("essays") or {})} or None
    writing = data.get("writing") or {}
    writing["voice"] = d.voice
    writing.setdefault("letter", {})
    writing["letter"].update({"length": d.letter_length, "structure": d.letter_structure,
                              "proof_asset": {name: t.proof_asset for name, t in tracks.items()}})
    writing["answers"] = {"why_role": d.why_role}
    writing["avoid"] = d.avoid
    data["writing"] = writing
    data.pop("_note", None)

    shipped = (yaml.safe_load(DEFAULTS.read_text(encoding="utf-8")) or {}).get("rejects") or {}
    places = [p for p in d.locations
              if answers.remote_ok or not (p.title or "remote" in p.label.lower())]
    abroad = any(country_of(place) == "elsewhere" for place in answers.locations)
    search = {
        "rejects": {"seniority": _rejects(d.reject_seniority, shipped.get("seniority") or []),
                    "off_function": _rejects(d.reject_functions, shipped.get("off_function") or []),
                    "too_technical": _rejects(d.reject_technical, shipped.get("too_technical") or [])},
        "geography": {_slug(p.label): {"label": p.label, "weight": p.weight,
                                       "patterns": [_rx(m) for m in p.match], "match_title": p.title}
                      for p in places},
        "role_fit": [[_bounded(w.match), w.weight] for w in d.roles],
        "timing": [[_bounded(w.match), w.weight] for w in d.timing],
        "title_timing": [[_bounded(w.match), w.weight] for w in d.title_timing],
        "tracks": {"default": default,
                   "kinds": {name: {"resume": t.resume, "code_link": t.code_link,
                                    "keywords": [[k.phrase, k.weight] for k in t.keywords]}
                             for name, t in tracks.items()}},
        "limits": {"max_years_experience": d.max_years_experience,
                   "advanced_degree_required": d.reject_advanced_degree,
                   "graduate_programs": d.reject_graduate_programs},
        "country": "elsewhere" if abroad else "us",
    }
    if abroad:
        search["non_us"] = []
    private = {"identity": {"phone": answers.phone or ASK, "street_address": answers.street_address or ASK},
               "education_private": {"gpa": answers.gpa or ASK}}
    return {"profile.yaml": data, "profile.private.yaml": private, "search.yaml": search}
