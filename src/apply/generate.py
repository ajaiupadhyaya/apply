"""Letter and resume generation: compose, lint, render, compile.

The order is deliberate. Text is composed in plain prose, linted in plain prose,
and only then escaped and pushed through LaTeX. Linting the .tex would mean
arguing with the preamble about whether 11pt is a hallucinated number.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .models import Posting, Track
from .profile import ASK, Profile

# ------------------------------------------------------------------ paths


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def templates_dir() -> Path:
    return repo_root() / "templates"


def out_dir() -> Path:
    """Where generated artifacts land. Overridable so tests never touch out/."""
    env = os.environ.get("APPLY_OUT_DIR")
    return Path(env).expanduser() if env else repo_root() / "out"


# ------------------------------------------------------------- latex escape

_LATEX_REPLACEMENTS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
_LATEX_RE = re.compile("|".join(re.escape(k) for k in _LATEX_REPLACEMENTS))

#: Characters a paste from a web page brings along that pdflatex will not accept
#: under T1/mathptmx. Mapped before escaping, since some map to LaTeX commands.
_TYPOGRAPHY = {
    "—": "---", "–": "--", "‒": "--", "−": "--",
    "‘": "`", "’": "'", "“": "``", "”": "''",
    "…": r"\ldots{}", " ": " ", "​": "",
    "•": "-", "·": "-", "′": "'", "­": "",
}


def latex_escape(value) -> str:
    """Make any string safe to drop into a .tex document.

    A company called `Smith & Co.` must not break the build, and neither must a
    posting that says `100% remote` or a role with an underscore in it.
    """
    if value is None:
        return ""
    text = str(value)
    for bad, good in _TYPOGRAPHY.items():
        text = text.replace(bad, good)
    return _LATEX_RE.sub(lambda m: _LATEX_REPLACEMENTS[m.group(0)], text)


def _env() -> Environment:
    """Jinja with LaTeX-safe delimiters.

    `{{ }}` and `{% %}` are a bad fit for a language whose grammar is braces.
    `<<x>>` and `<% %>` never occur in LaTeX, and unlike the \\VAR{} convention
    they leave the template readable to whoever edits it next.
    """
    env = Environment(
        loader=FileSystemLoader(str(templates_dir())),
        block_start_string="<%", block_end_string="%>",
        variable_start_string="<<", variable_end_string=">>",
        comment_start_string="<#", comment_end_string="#>",
        trim_blocks=True, lstrip_blocks=True,
        autoescape=False, undefined=StrictUndefined,
        keep_trailing_newline=True,
    )
    # Escaping is the default, not something a template has to remember.
    env.filters["tex"] = latex_escape
    env.finalize = latex_escape
    return env


# ------------------------------------------------------------- the JD anchor

_H = r"[^\S\n]+"   # whitespace that is not a line break
_PROPER_RUN = re.compile(
    rf"\b([A-Z][A-Za-z]+(?:{_H}(?:and|of|for|the){_H}[A-Z][A-Za-z]+|{_H}[A-Z][A-Za-z]+){{1,3}})\b"
)
_PROPER_ONE = re.compile(r"\b([A-Z][A-Za-z]{3,})\b")
_STRUCTURE = re.compile(
    r"\b(?:the|our|its|their)\s+((?:[a-z][a-z'\u2019-]*\s+){0,3}"
    r"(?:platform|pool|team|desk|group|program|model|mandate|portfolio|process|"
    r"structure|book|franchise|engine|committee|office|strategy|business))\b"
)

_ANCHOR_STOP = {
    # Calendar and boilerplate.
    "january", "february", "march", "april", "may", "june", "july", "august",
    "september", "october", "november", "december", "monday", "tuesday",
    "wednesday", "thursday", "friday", "equal opportunity", "equal opportunity employer",
    "united states", "bachelor", "bachelors", "master", "masters", "about",
    "responsibilities", "qualifications", "requirements", "overview", "summary",
    "compensation", "benefits", "location", "locations", "apply", "deadline",
    "application deadline", "what you will do", "what we look for", "hours", "pay",
    # Section headings and generic nouns that carry no information.
    "the role", "this role", "the team", "the firm", "the company", "the program",
    "the position", "the successful candidate", "seed fixture", "strong written",
}


#: Fine inside a longer name ("Risk and Quantitative Analysis"), useless alone.
_WEAK_SINGLETONS = {
    "risk", "investment", "investments", "committee", "analysis", "management",
    "portfolio", "team", "group", "business", "businesses", "markets", "market",
    "research", "data", "client", "clients", "technology", "finance", "financial",
    "company", "firm", "office", "work", "experience", "skills", "strong",
    "bachelor", "degree", "students", "student", "responsibilities", "support",
    "development", "operations", "strategy", "strategies", "assets", "capital",
    # Sentence-initial function words, which a capitalisation heuristic loves.
    "what", "when", "where", "which", "while", "with", "this", "that", "these",
    "those", "your", "you", "our", "ours", "their", "they", "we", "who", "how",
    "why", "the", "there", "here", "about", "also", "both", "each", "every",
    "from", "into", "must", "please", "some", "such", "then", "they", "will",
    "would", "should", "could", "candidates", "applicants", "interested",
}

#: Words that mean "this is the job posting", not "this is why you would take it".
_GENERIC_ROLE_WORDS = {
    "analyst", "analysts", "intern", "interns", "internship", "associate",
    "associates", "program", "programme", "position", "role", "candidate",
    "candidates", "applicant", "applicants", "employer", "employee", "employees",
    "job", "jobs", "hiring", "recruiting", "resume", "cv", "salary", "hours",
    "summer", "full-time", "fulltime", "part-time",
}


@dataclass(slots=True)
class Anchor:
    phrase: str
    weight: int
    where: int

    def sentence_case(self) -> str:
        """Capitalise only the first letter; leave proper nouns alone."""
        return self.phrase[0].upper() + self.phrase[1:]

    @property
    def with_article(self) -> str:
        """The form that reads as English inside a sentence.

        "Aladdin Engineering" is a name and stands alone. "Investment Committee"
        is a department, and "because of Investment Committee" is not a sentence
        anyone writes, so it gets its article back.
        """
        if self.phrase[:4].lower() in ("the ", "our ", "its "):
            return self.phrase
        content = [
            w for w in (x.lower().strip(".,()") for x in self.phrase.split())
            if w not in {"and", "of", "for", "the"}
        ]
        if content and all(w in _WEAK_SINGLETONS for w in content):
            return f"the {self.phrase}"
        return self.phrase


def jd_anchors(jd: str, company: str | None = None, role: str | None = None,
               location: str | None = None) -> list[Anchor]:
    """Specific, verifiable things the posting names: a platform, a mandate, a
    structure. Ranked. Paragraph 4 cites the best one, and `apply show` prints
    the list so the owner can pick a different one."""
    from .parse import _STATE_NAMES, _STATES

    # Whole phrases that are never an anchor.
    banned_phrases = set(_ANCHOR_STOP)
    for source in (company, role, location):
        if source:
            banned_phrases.add(source.lower())

    # A phrase containing any of these is disqualified: it is naming the
    # employer, the place, or the job, none of which is a reason to apply.
    banned_words = {w for w in _ANCHOR_STOP if " " not in w}
    banned_words |= _GENERIC_ROLE_WORDS
    banned_words |= {s.lower() for s in _STATE_NAMES}
    banned_words |= {s.lower() for s in _STATES}
    for source in (company, location):
        if source:
            banned_words.update(w.lower().strip(".,'()") for w in source.split())

    found: dict[str, Anchor] = {}

    def offer(phrase: str, weight: int, where: int) -> None:
        phrase = re.sub(r"[^\S\n]+", " ", phrase).strip(" .,:;")
        key = phrase.lower()
        if len(phrase) < 4 or key in banned_phrases:
            return
        if any(w.strip(".,'()") in banned_words for w in key.split()):
            return
        prior = found.get(key)
        if prior is None or weight > prior.weight:
            found[key] = Anchor(phrase, weight, where)

    counts: dict[str, int] = {}
    for m in _PROPER_ONE.finditer(jd):
        counts[m.group(1)] = counts.get(m.group(1), 0) + 1

    for m in _PROPER_RUN.finditer(jd):
        offer(m.group(1), 5, m.start())
    for m in _STRUCTURE.finditer(jd):
        phrase = m.group(1)
        # "the platform" says nothing; "the long-term pool" says something.
        offer(f"the {phrase}", 4 if len(phrase.split()) > 1 else 2, m.start())
    for token, n in counts.items():
        # A capitalised word the posting keeps saying is often a named system —
        # Aladdin, Bloomberg, Athena. But a sentence-initial common noun is not,
        # and "Investment is the specific draw" is not a sentence worth sending.
        if n >= 2 and token.lower() not in banned_words \
                and token.lower() not in _WEAK_SINGLETONS:
            offer(token, 4, jd.find(token))

    return sorted(found.values(), key=lambda a: (-a.weight, a.where))


# -------------------------------------------------------------------- lint

PROHIBITED = [
    "passionate", "dynamic", "synergy", "leverage my skills",
    "fast-paced environment", "i believe i would be a great fit",
]

#: Praise. Allowed only where the posting said it first.
SUPERLATIVES = [
    "leading", "premier", "world-class", "world class", "best-in-class",
    "best in class", "top-tier", "top tier", "renowned", "prestigious",
    "foremost", "unparalleled", "elite", "cutting-edge", "cutting edge",
    "industry-leading", "industry leading", "most respected", "storied",
]

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9./,%$+-]*")


@dataclass(slots=True)
class LintResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors

    def __bool__(self) -> bool:
        return self.ok


def _boundary(phrase: str) -> re.Pattern:
    return re.compile(rf"(?<![A-Za-z0-9]){re.escape(phrase)}(?![A-Za-z0-9])", re.I)


_PROHIBITED_RE = [(p, _boundary(p)) for p in PROHIBITED]
_SUPERLATIVE_RE = [(p, _boundary(p)) for p in SUPERLATIVES]


def _digit_tokens(text: str) -> set[str]:
    return {
        t.strip(".,").lower()
        for t in _TOKEN.findall(text)
        if any(c.isdigit() for c in t)
    }


def lint(body: str, profile: Profile, posting: Posting) -> LintResult:
    """The gate between a generated letter and a PDF.

    Errors stop the build. Warnings do not — a letter that cannot be printed
    cannot be read, and reading it is the point of the review gate.
    """
    result = LintResult()

    for phrase, pattern in _PROHIBITED_RE:
        if pattern.search(body):
            result.errors.append(f'prohibited phrase: "{phrase}"')

    jd_lower = posting.jd_raw.lower()
    for phrase, pattern in _SUPERLATIVE_RE:
        if pattern.search(body) and phrase.lower() not in jd_lower:
            result.errors.append(
                f'superlative "{phrase}" is not in the posting — say something '
                f"checkable or say nothing"
            )

    # Hallucination guard. A number may come from the profile, the context
    # documents, or the posting itself; a number from none of them was invented.
    #
    # The company and role count as part of the posting. Without them a firm
    # whose name contains a digit — 3M, 7-Eleven, 1-800-Flowers — gets its own name
    # reported as an invented figure whenever the description does not happen
    # to repeat it.
    from .context import sourced_text

    sourced = (
        profile.sourced_tokens
        | _digit_tokens(sourced_text(profile))
        | _digit_tokens(posting.jd_raw)
        | _digit_tokens(f"{posting.company} {posting.role}")
    )
    for token in sorted(_digit_tokens(body)):
        if token not in sourced:
            result.errors.append(
                f'unsourced figure "{token}" — it appears in neither the profile, '
                f"the context documents, nor the job description"
            )

    # The one statement where a wrong answer is disqualifying gets a
    # deterministic check of its own, on top of the verifier's.
    result.errors += _sponsorship_errors(body, profile)

    if ASK in body:
        result.errors.append(
            "the text still contains an ASK placeholder from profile.yaml"
        )
    return result


_NEGATION = re.compile(r"\b(not|no|never|without|won't|will\s+not|do\s+not|does\s+not)\b|n't\b", re.I)


def _sponsorship_errors(text: str, profile: Profile) -> list[str]:
    """Any sentence about sponsorship must agree with the profile."""
    errors = []
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if not re.search(r"sponsor", sentence, re.I):
            continue
        negated = bool(_NEGATION.search(sentence))
        if not profile.needs_sponsorship_ever and not negated:
            errors.append(
                f'says sponsorship would be needed, but the profile says it will not '
                f'be: "{sentence.strip()[:120]}"')
        if profile.needs_sponsorship_ever and negated:
            errors.append(
                f'says sponsorship is not needed, but the profile says it will be: '
                f'"{sentence.strip()[:120]}"')
    return errors


# ------------------------------------------------------------------ letter


@dataclass(slots=True)
class Letter:
    """A letter ready to typeset: Claude's paragraphs inside a fixed frame.

    The frame — salutation and sign-off — is typography, not prose, so it is the
    only part not written by the model.
    """

    paragraphs: list[str]
    closing: str
    salutation: str = "Dear Hiring Committee,"
    signoff: str = "Sincerely,"
    anchor: Anchor | None = None

    @property
    def body(self) -> str:
        return "\n\n".join(self.paragraphs)

    @property
    def full_text(self) -> str:
        return "\n\n".join([*self.paragraphs, self.closing])


def _collapse(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def frame(to: str | None = None) -> tuple[str, str]:
    """(salutation, sign-off). Addressed to a person when one is known."""
    return (f"Dear {to}," if to else "Dear Hiring Committee,"), "Sincerely,"


def letter_from_package(package, *, to: str | None = None) -> Letter:
    salutation, signoff = frame(to)
    return Letter(
        paragraphs=[_collapse(p) for p in package.paragraphs()],
        closing=_collapse(package.closing),
        salutation=salutation,
        signoff=signoff,
        anchor=Anchor(package.anchor_used, 9, 0) if package.anchor_used else None,
    )


def package_from_files(directory: Path):
    """Read a hand-edited body.md (and answers.md, if present) back into a Package.

    body.md is blank-line-separated paragraphs; the last one is the closing.
    answers.md holds the two portal answers under their headings.
    """
    from .llm import Package

    body_path = directory / "body.md"
    if not body_path.exists():
        raise FileNotFoundError(
            f"{body_path} does not exist. Run `apply gen <slug>` first, or save the "
            f"letter body there yourself: paragraphs separated by blank lines, the "
            f"last one being the closing.")
    paragraphs = [_collapse(p) for p in re.split(r"\n\s*\n", body_path.read_text())
                  if p.strip() and not p.lstrip().startswith("<!--")]
    if len(paragraphs) < 2:
        raise ValueError(f"{body_path} needs at least a body paragraph and a closing.")
    closing, body = paragraphs[-1], paragraphs[:-1]
    if len(body) > 4:
        body = body[:3] + [" ".join(body[3:])]
    body += [""] * (4 - len(body))

    short = long = ""
    answers_path = directory / "answers.md"
    if answers_path.exists():
        sections = re.split(r"(?m)^##\s+", answers_path.read_text())
        for section in sections:
            head, _, text = section.partition("\n")
            if "short" in head.lower():
                short = _collapse(text)
            elif "long" in head.lower():
                long = _collapse(text)

    return Package(
        paragraph_1=body[0], paragraph_2=body[1], paragraph_3=body[2],
        paragraph_4=body[3], closing=closing, proof_asset="", anchor_used="",
        why_role_short=short, why_role_long=long,
        notes="edited by hand",
    )


def write_body_files(package, directory: Path) -> tuple[Path, Path]:
    """body.md and answers.md: the editable copies of what was written."""
    body = directory / "body.md"
    body.write_text(
        "<!-- Edit freely, then: apply gen <slug> --from-body\n"
        "     Paragraphs are separated by blank lines; the last is the closing.\n"
        "     Your edits are checked by the lint and audited by Claude, never "
        "rewritten. -->\n\n"
        + "\n\n".join([*package.paragraphs(), package.closing]) + "\n")
    answers = directory / "answers.md"
    answers.write_text(
        "## Why this role (short)\n\n" + package.why_role_short.strip()
        + "\n\n## Why this role (long)\n\n" + package.why_role_long.strip() + "\n")
    return body, answers


# ------------------------------------------------------------- rendering


class Raw(str):
    """A string that must reach LaTeX unescaped — a URL inside \\url{}, mainly."""


def _finalize(value):
    return str(value) if isinstance(value, Raw) else latex_escape(value)


def _contact_bits(profile: Profile, *, with_portfolio: bool = True) -> list[str]:
    bits = [profile.email]
    if profile.phone:
        bits.append(profile.phone)
    if profile.location_line:
        bits.append(profile.location_line)
    portfolio = profile.links.get("portfolio")
    if with_portfolio and portfolio:
        bits.append(re.sub(r"^https?://", "", portfolio).rstrip("/"))
    return bits


def _human_date(d: _dt.date | None = None) -> str:
    d = d or _dt.date.today()
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def render_letter(profile: Profile, posting: Posting, letter: Letter) -> str:
    """Track template + the written paragraphs -> LaTeX source."""
    env = _env()
    env.finalize = _finalize
    template = env.get_template(f"letters/{posting.track}.tex.j2")

    # The quant template offers a link to the code when paragraph 2 is about a
    # project that has one. Claude names its proof asset; match it to a project.
    proof_url = None
    body = letter.full_text.lower()
    for project in profile.projects.values():
        if project.url and project.name.lower() in body and "quant" in project.tracks:
            proof_url = project.url
            break

    return template.render(
        name=profile.display_name,
        contact_bits=_contact_bits(profile),
        contact_line=" · ".join(_contact_bits(profile)),
        date_line=_human_date(),
        recipient=None,
        company=posting.company,
        company_location=posting.location,
        salutation=letter.salutation,
        paragraphs=letter.paragraphs,
        closing=letter.closing,
        signoff=letter.signoff,
        proof_url=proof_url,
        proof_url_raw=Raw(proof_url) if proof_url else None,
    )


RESUME_VARIANT = {
    Track.QUANT: "resume_quant",
    Track.BANKING: "resume_traditional",
    Track.ALLOCATOR: "resume_traditional",
    Track.CORPORATE: "resume_traditional",
}


def select_resume(track: Track | str) -> str:
    # Track subclasses str, so isinstance(track, str) is True for members too —
    # check for the enum first or `Track.QUANT` round-trips through "Track.QUANT".
    return RESUME_VARIANT[track if isinstance(track, Track) else Track.parse(track)]


_MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _month_year(value) -> str | None:
    """'2025-08' -> 'Aug 2025'. 'present' -> 'Present'. ASK -> None."""
    if value in (None, "", ASK):
        return None
    if isinstance(value, _dt.date):
        return f"{_MONTH_ABBR[value.month - 1]} {value.year}"
    text = str(value).strip()
    if text.lower() in ("present", "current", "now"):
        return "Present"
    m = re.match(r"^(\d{4})-(\d{1,2})", text)
    if m:
        return f"{_MONTH_ABBR[int(m.group(2)) - 1]} {m.group(1)}"
    return text


def _resume_context(profile: Profile) -> tuple[dict, list[str]]:
    """Pre-format everything date-shaped in Python. Templates lay out; they do
    not do arithmetic, and they do not decide what a missing date means."""
    warnings: list[str] = []

    education = []
    for i, e in enumerate(profile.education):
        detail = []
        if e.get("degree"):
            detail.append(e["degree"] + (f", {e['major']}" if e.get("major") else ""))
        if e.get("note"):
            detail.append(e["note"][0].upper() + e["note"][1:])
        right = None
        if e.get("current"):
            right = f"Expected {profile.grad_month_year}"
            if profile.gpa:
                detail.append(f"GPA {profile.gpa}")
        education.append({
            "institution": e.get("institution", ""),
            "detail": " \u00b7 ".join(detail),
            "right": right,
        })

    experience = []
    for i, x in enumerate(profile.experience):
        start, end = _month_year(x.get("start")), _month_year(x.get("end"))
        if start is None:
            warnings.append(
                f"experience[{i}].start is still ASK — the resume will show "
                f"\"{end or 'Present'}\" with no start date"
            )
        dates = " \u2013 ".join(d for d in (start, end) if d) or None
        experience.append({
            "org": x.get("org", ""), "title": x.get("title", ""),
            "location": x.get("location"), "dates": dates,
            "bullets": [re.sub(r"\s+", " ", b).strip() for b in (x.get("bullets") or [])],
        })

    skills = {k: v for k, v in (profile.raw.get("skills") or {}).items() if v}
    return {
        "name": profile.display_name,
        # The resume prints links on their own line, so the contact line
        # does not repeat the portfolio URL.
        "contact_bits": _contact_bits(profile, with_portfolio=False),
        "links": profile.links,
        "education": education,
        "experience": experience,
        "projects": list(profile.projects.values()),
        "skills": skills,
    }, warnings


def render_resume(profile: Profile, variant: str) -> tuple[str, list[str]]:
    env = _env()
    env.finalize = _finalize
    template = env.get_template(f"resumes/{variant}.tex.j2")
    context, warnings = _resume_context(profile)
    return template.render(**context), warnings


# -------------------------------------------------------------- compiling


class CompileError(RuntimeError):
    pass


def _log_tail(log: Path, lines: int = 30) -> str:
    if not log.exists():
        return "(no log written)"
    text = log.read_text(errors="replace").splitlines()
    interesting = [l for l in text if l.startswith("!") or "Error" in l or "error" in l]
    tail = interesting[-lines:] or text[-lines:]
    return "\n".join(tail)


def compile_pdf(tex_path: Path, *, max_pages: int | None = 1) -> Path:
    """pdflatex twice, then check the page count. Returns the PDF path.

    Two passes because hyperref writes an .aux on the first one. Compiling into a
    scratch directory keeps .aux/.log/.out out of out/<slug>/, which the owner
    opens by hand.
    """
    if shutil.which("pdflatex") is None:
        raise CompileError(
            "pdflatex is not on PATH. Install MacTeX (`brew install --cask mactex-no-gui`) "
            "or BasicTeX, then reopen the shell."
        )
    tex_path = Path(tex_path)
    with tempfile.TemporaryDirectory(prefix="apply-tex-") as tmp:
        tmpdir = Path(tmp)
        shutil.copy(tex_path, tmpdir / tex_path.name)
        for _ in range(2):
            proc = subprocess.run(
                ["pdflatex", "-interaction=nonstopmode", "-halt-on-error",
                 "-output-directory", str(tmpdir), str(tmpdir / tex_path.name)],
                capture_output=True, text=True,
            )
            if proc.returncode != 0:
                raise CompileError(
                    f"pdflatex failed on {tex_path.name}:\n"
                    + _log_tail(tmpdir / (tex_path.stem + ".log"))
                )
        built = tmpdir / (tex_path.stem + ".pdf")
        if not built.exists():
            raise CompileError(f"pdflatex produced no PDF for {tex_path.name}")
        pages = page_count(built)
        if max_pages is not None and pages > max_pages:
            raise CompileError(
                f"{tex_path.stem} compiled to {pages} pages; the limit is {max_pages}. "
                f"Cut the letter, do not widen the margins."
            )
        final = tex_path.with_suffix(".pdf")
        shutil.copy(built, final)
    return final


def page_count(pdf: Path) -> int:
    from pypdf import PdfReader

    return len(PdfReader(str(pdf)).pages)


# ---------------------------------------------------------- orchestration

_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9]+")


def _safe(text: str) -> str:
    return _FILENAME_SAFE.sub("_", text).strip("_") or "Untitled"


#: Words that make a filename longer without making it clearer.
_FILLER = {"the", "a", "an", "of", "for", "and", "to", "in", "at", "program",
           "programme", "position", "role", "opportunity", "full", "time",
           "fulltime", "summer", "intern", "internship", "20", "2026", "2027"}


def _document_tag(posting: Posting, words: int = 3) -> str:
    """Company plus enough of the role to tell two letters apart."""
    company = _safe(posting.company)
    significant = [
        w for w in _FILENAME_SAFE.sub(" ", posting.role or "").split()
        if w.lower() not in _FILLER and len(w) > 1
    ][:words]
    return f"{company}_{_safe(' '.join(significant))}" if significant else company


def _sweep(directory: Path, *, keep: Path, kind: str) -> None:
    """Delete this folder's older PDFs of the same kind.

    A renamed document leaves its predecessor behind, and a folder holding both
    Cover_Letter_Acme.pdf and
    Cover_Letter_Acme_Quantitative_Research.pdf is a folder you
    will eventually upload the wrong file from. Scoped to one slug's directory
    and one document kind; nothing else is ever removed.
    """
    for candidate in directory.glob(f"*_{kind}_*.pdf"):
        if candidate != keep:
            candidate.unlink(missing_ok=True)


@dataclass(slots=True)
class Artifacts:
    slug: str
    directory: Path
    letter_tex: Path
    letter_pdf: Path | None = None
    resume_tex: Path | None = None
    resume_pdf: Path | None = None
    resume_variant: str = ""
    fieldpack: Path | None = None
    prompt_md: Path | None = None
    posting_md: Path | None = None
    body_md: Path | None = None
    answers_md: Path | None = None
    verification: Path | None = None
    lint: LintResult = field(default_factory=LintResult)
    anchors: list[Anchor] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    source: str = "api"          # api | body.md | prompt
    written: object | None = None

    @property
    def ok(self) -> bool:
        return self.letter_pdf is not None

    @property
    def status(self) -> str:
        if self.source == "prompt":
            return "prompt"
        return getattr(self.written, "status", "unavailable")

    @property
    def usage(self):
        return getattr(self.written, "usage", None)


def _posting_md(posting: Posting, anchors: list[Anchor]) -> str:
    lines = [
        f"# {posting.company} — {posting.role}",
        "",
        f"- **slug**: `{posting.slug}`",
        f"- **track**: {posting.track}",
        f"- **deadline**: {posting.deadline or 'NOT STATED — verify manually'}",
        f"- **location**: {posting.location or '—'}",
        f"- **comp**: {posting.comp or '—'}",
        f"- **source**: {posting.source or '—'} {posting.source_url or ''}".rstrip(),
        "",
        "## Anchors found in the posting",
        "",
    ]
    lines += [f"- {a.with_article}" for a in anchors[:6]] or ["- (none)"]
    lines += ["", "## Job description (verbatim)", "", "```", posting.jd_raw, "```", ""]
    return "\n".join(lines)


def write_prompt(profile: Profile, posting: Posting, anchors: list[str],
                 directory: Path, to: str | None = None) -> Path:
    """The exact request the API would receive, for pasting by hand.

    Paste it into Claude Code or claude.ai, save the letter body to body.md
    (paragraphs separated by blank lines, the closing last), then run
    `apply gen <slug> --from-body`.
    """
    from .writer import prompts

    system, user = prompts(profile, posting, anchors, to)
    text = "\n\n".join([
        f"# Application — {posting.company}, {posting.role}",
        "Paste everything below the line into Claude. Save the letter body it "
        f"returns to `out/{posting.slug}/body.md` — paragraphs separated by blank "
        "lines, the closing last — then run:",
        f"    apply gen {posting.slug} --from-body",
        "---",
        *(block["text"] for block in system),
        user,
    ])
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "PROMPT.md"
    path.write_text(text + "\n")
    return path


def _pages_for(profile: Profile, posting: Posting, letter: Letter) -> int:
    """Render and compile a draft somewhere disposable; count its pages."""
    with tempfile.TemporaryDirectory(prefix="apply-fit-") as tmp:
        tex = Path(tmp) / "fit.tex"
        tex.write_text(render_letter(profile, posting, letter))
        return page_count(compile_pdf(tex, max_pages=None))


def _clear_pdfs(directory: Path) -> None:
    """A refused draft must not leave yesterday's PDF looking current."""
    for kind in ("Cover_Letter", "Resume"):
        for stale in directory.glob(f"*_{kind}_*.pdf"):
            stale.unlink(missing_ok=True)
    (directory / "cover_letter.pdf").unlink(missing_ok=True)


def build(
    profile: Profile,
    posting: Posting,
    *,
    llm: str = "api",
    from_body: bool = False,
    to: str | None = None,
    anchor_override: str | None = None,
    model: str | None = None,
    effort: str = "high",
    skip_resume: bool = False,
    budget=None,
    caller=None,
) -> Artifacts:
    """Produce every artifact for one application. Touches no database rows.

    The caller owns the state machine; this function owns the files. That split
    is what makes it impossible for a regeneration to quietly mark something
    reviewed.

    `llm="api"` has Claude write and a second request audit. `llm="manual"`
    writes PROMPT.md and stops. `from_body=True` takes a hand-edited body.md,
    runs the free checks, and has Claude audit it if a key is available —
    without ever rewriting it.
    """
    import json

    from . import fieldpack as fieldpack_mod
    from . import llm as llm_mod
    from . import writer

    directory = out_dir() / posting.slug
    directory.mkdir(parents=True, exist_ok=True)

    anchors = jd_anchors(posting.jd_raw, posting.company, posting.role, posting.location)
    if anchor_override:
        anchors = [Anchor(anchor_override, 9, 0), *anchors]
    phrases = [a.with_article for a in anchors]

    artifacts = Artifacts(slug=posting.slug, directory=directory,
                          letter_tex=directory / "cover_letter.tex", anchors=anchors)
    artifacts.posting_md = directory / "posting.md"
    artifacts.posting_md.write_text(_posting_md(posting, anchors))

    if llm == "manual" and not from_body:
        artifacts.source = "prompt"
        artifacts.prompt_md = write_prompt(profile, posting, phrases, directory, to)
        return artifacts

    def lint_check(package) -> list[str]:
        return lint(writer.full_text(package), profile, posting).errors

    def fit_check(package) -> int:
        return _pages_for(profile, posting, letter_from_package(package, to=to))

    options: dict = {}
    if caller is not None:
        options["caller"] = caller
    if from_body:
        artifacts.source = "body.md"
        options.update(first_draft=package_from_files(directory), max_drafts=1,
                       verify=(llm != "manual") and (caller is not None or llm_mod.available()))
    elif caller is None and not llm_mod.available():
        raise llm_mod.LLMUnavailable(llm_mod.NO_CREDENTIAL)

    written = writer.write(
        profile, posting, lint=lint_check, fit=fit_check, anchors=phrases, to=to,
        budget=budget, model=model or llm_mod.DEFAULT_MODEL, effort=effort, **options,
    )
    artifacts.written = written

    artifacts.verification = directory / "verification.json"
    artifacts.verification.write_text(json.dumps(written.as_record(), indent=2) + "\n")

    if written.package is not None:
        artifacts.lint = lint(writer.full_text(written.package), profile, posting)
        if not from_body:
            artifacts.body_md, artifacts.answers_md = write_body_files(
                written.package, directory)
    else:
        artifacts.lint = LintResult(errors=[written.reason or "nothing was written"])

    if not written.ok:
        _clear_pdfs(directory)
        return artifacts

    letter = letter_from_package(written.package, to=to)
    artifacts.letter_tex.write_text(render_letter(profile, posting, letter))
    final = directory / f"{profile.file_name}_Cover_Letter_{_document_tag(posting)}.pdf"
    compile_pdf(artifacts.letter_tex, max_pages=1).replace(final)
    artifacts.letter_pdf = final
    _sweep(directory, keep=final, kind="Cover_Letter")

    if not skip_resume:
        variant = select_resume(posting.track)
        artifacts.resume_variant = variant
        source_tex, resume_warnings = render_resume(profile, variant)
        artifacts.warnings += resume_warnings
        artifacts.resume_tex = directory / f"{variant}.tex"
        artifacts.resume_tex.write_text(source_tex)
        target = directory / f"{profile.file_name}_Resume_{_document_tag(posting)}.pdf"
        compile_pdf(artifacts.resume_tex, max_pages=1).replace(target)
        artifacts.resume_pdf = target
        _sweep(directory, keep=target, kind="Resume")

    artifacts.fieldpack = fieldpack_mod.write(
        profile, posting, directory,
        answers={"short": written.package.why_role_short,
                 "long": written.package.why_role_long},
    )
    if written.package.notes.strip() and written.package.notes.strip() != "edited by hand":
        artifacts.warnings.append(f"writer's note: {written.package.notes.strip()}")
    return artifacts
