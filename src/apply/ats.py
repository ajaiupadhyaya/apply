"""What an applicant-tracking system sees in the resume, and what it looks for.

An ATS reads the PDF's text layer, not the page. LaTeX can produce a resume that
looks right and extracts wrong: `(cid:NN)` glyph markers where a font has no
Unicode map, an email that exists only as a hyperlink target, a date range joined
by the en-dash `--` becomes, which at least one Workday import split on U+002D
only and dropped along with the dates. Everything here is deterministic and free.

The keyword half answers one question per term the posting names: is it on the
resume, is it something the owner has but the resume does not say, or is it a
real gap. Gaps are never "fixed" here — a gap is a gap, and the letter is where
it gets an honest bridge. Across postings the gaps add up to `apply gaps`, which
is a learning plan rather than a keyword-stuffing list.

Adapted from MadsLorentzen/ai-job-search (tools/verify_pdf.py and the /apply
ATS step), reduced to the checks a single-column pdflatex resume can fail.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

# ------------------------------------------------------------- text layer

#: The dashes a year must never be joined to. U+2013 is what LaTeX makes of `--`.
NON_ASCII_DASHES = "‐‑‒–—―−"
_YEAR = r"(?<!\d)(?:19|20)\d{2}(?!\d)"
#: Horizontal whitespace only: a year ending one line must not join a dash
#: opening the next (a bullet, a wrapped line).
_DATE_RANGE = re.compile(
    rf"{_YEAR}[^\S\n]*[{NON_ASCII_DASHES}]|[{NON_ASCII_DASHES}][^\S\n]*{_YEAR}"
)
#: What a font without a ToUnicode map, or a broken encoding, leaves behind.
_GARBAGE = re.compile(r"\(cid:\d+\)|�")

_FOLDS = str.maketrans({"‘": "'", "’": "'", "“": '"', "”": '"',
                        "–": "-", "—": "-", " ": " "})


def normalize(text: str) -> str:
    """Fold for comparison only: NFC, LaTeX's typographic substitutions, whitespace."""
    text = unicodedata.normalize("NFC", text).translate(_FOLDS)
    return " ".join(text.split())


def extract(pdf: Path) -> str:
    from pypdf import PdfReader

    reader = PdfReader(str(pdf))
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def non_ascii_date_ranges(text: str) -> list[str]:
    """Each line of the RAW text layer where a year touches a Unicode dash."""
    hits: list[str] = []
    for match in _DATE_RANGE.finditer(text):
        start = text.rfind("\n", 0, match.start()) + 1
        end = text.find("\n", match.end())
        line = " ".join(text[start:end if end != -1 else len(text)].split())
        if line not in hits:
            hits.append(line)
    return hits


def _digits(value: str) -> str:
    return re.sub(r"\D", "", value)


def parse_problems(text: str, *, email: str | None, phone: str | None) -> list[str]:
    """Everything that would make an ATS misread this resume. Empty means clean."""
    problems: list[str] = []
    folded = normalize(text)
    if not folded:
        return ["the resume has no extractable text at all — an ATS sees a blank page"]
    garbage = _GARBAGE.findall(text)
    if garbage:
        problems.append(f"{len(garbage)} unreadable glyph(s) such as {garbage[0]!r} in "
                        f"the text layer — a font is missing its Unicode map")
    if email and email.lower() not in folded.lower():
        problems.append(f"the email {email} is not in the text layer as literal text")
    if phone and _digits(phone) and _digits(phone) not in _digits(folded):
        problems.append("the phone number is not in the text layer as literal digits")
    for line in non_ascii_date_ranges(text):
        problems.append(f"date range joined by a non-ASCII dash, which some ATS "
                        f"imports drop: {line[:80]!r}")
    return problems


# --------------------------------------------------------------- keywords

#: term -> regex. Tools and methods a finance or quant posting names as a
#: requirement. Short or symbol-bearing names get explicit boundaries; the rest
#: match case-insensitively on word boundaries. Extend freely — a term that is
#: never named in a posting costs nothing.
_VOCAB_SPEC: dict[str, str] = {
    "Python": r"python",
    "R": r"(?<![&/])R(?![&/+'’-])",
    "SQL": r"sql",
    "C++": r"c\+\+",
    "C#": r"c#",
    "Java": r"java(?!script)",
    "JavaScript": r"javascript|typescript",
    "OCaml": r"ocaml",
    "MATLAB": r"matlab",
    "VBA": r"vba|visual basic",
    "Excel": r"excel(?!lence|lent)",
    "PowerPoint": r"powerpoint",
    "Tableau": r"tableau",
    "Power BI": r"power\s?bi",
    "pandas": r"pandas",
    "NumPy": r"numpy",
    "Git": r"git(?!hub)|github",
    "Linux": r"linux|unix",
    "AWS": r"aws|amazon web services",
    "Spark": r"(?<!\w)spark",
    "Bloomberg": r"bloomberg",
    "FactSet": r"factset",
    "Capital IQ": r"capital\s?iq|capiq",
    "PitchBook": r"pitchbook",
    "Morningstar": r"morningstar",
    "WRDS": r"wrds",
    "Refinitiv": r"refinitiv|eikon",
    "financial modeling": r"financial model(?:l?ing)?|three[- ]statement model",
    "DCF": r"dcf|discounted cash flow",
    "LBO": r"lbo|leveraged buyout",
    "valuation": r"valuation",
    "accounting": r"accounting",
    "statistics": r"statistic(?:s|al)",
    "probability": r"probability",
    "econometrics": r"econometric",
    "machine learning": r"machine learning",
    "time series": r"time[- ]series",
    "stochastic calculus": r"stochastic calculus",
    "linear algebra": r"linear algebra",
    "optimization": r"optimi[sz]ation",
    "derivatives": r"derivatives?\b(?! of)",
    "fixed income": r"fixed income",
    "options": r"options pricing|option pricing|options? trading",
    "portfolio construction": r"portfolio construction",
    "risk management": r"risk management",
    "asset allocation": r"asset allocation",
    "due diligence": r"due diligence",
    "CFA": r"CFA",
    "SIE": r"SIE",
}

#: Acronyms that are ordinary words in lower case ("r", "sie") match exactly.
_CASE_SENSITIVE = {"R", "CFA", "SIE"}

VOCAB: dict[str, re.Pattern] = {
    term: re.compile(rf"(?<!\w)(?:{pattern})(?!\w)",
                     0 if term in _CASE_SENSITIVE else re.IGNORECASE)
    for term, pattern in _VOCAB_SPEC.items()
}


def terms_in(text: str) -> list[str]:
    folded = normalize(text)
    return [term for term, rx in VOCAB.items() if rx.search(folded)]


@dataclass(slots=True)
class Coverage:
    """Every vocabulary term the posting names, sorted into three piles."""

    covered: list[str] = field(default_factory=list)  # on the resume
    unused: list[str] = field(default_factory=list)   # in the sources, not on the resume
    gaps: list[str] = field(default_factory=list)     # nowhere: a real gap

    @property
    def named(self) -> int:
        return len(self.covered) + len(self.unused) + len(self.gaps)

    def summary(self) -> str | None:
        if not self.named:
            return None
        parts = [f"{len(self.covered)}/{self.named} of the posting's named skills are on the resume"]
        if self.unused:
            parts.append("you have but the resume omits: " + ", ".join(self.unused))
        if self.gaps:
            parts.append("gaps (address honestly, never stuff): " + ", ".join(self.gaps))
        return "; ".join(parts)


def coverage(jd: str, resume_text: str, sources: str) -> Coverage:
    result = Coverage()
    resume_terms = set(terms_in(resume_text))
    source_terms = set(terms_in(sources))
    for term in terms_in(jd):
        if term in resume_terms:
            result.covered.append(term)
        elif term in source_terms:
            result.unused.append(term)
        else:
            result.gaps.append(term)
    return result


def gaps(jd: str, sources: str) -> list[str]:
    """Terms the posting names that appear nowhere in the owner's sources."""
    have = set(terms_in(sources))
    return [t for t in terms_in(jd) if t not in have]


# ----------------------------------------------------------------- report


@dataclass(slots=True)
class Report:
    problems: list[str]
    coverage: Coverage

    def as_record(self) -> dict:
        return {"problems": self.problems, "coverage": asdict(self.coverage)}

    def notes(self) -> list[str]:
        out = [f"ats: {p}" for p in self.problems]
        summary = self.coverage.summary()
        if summary:
            out.append(f"keywords: {summary}")
        return out


def check(pdf: Path, *, jd: str, sources: str, email: str | None,
          phone: str | None) -> Report:
    text = extract(pdf)
    return Report(problems=parse_problems(text, email=email, phone=phone),
                  coverage=coverage(jd, text, sources))
