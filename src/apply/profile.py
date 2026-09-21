"""Loads profile.yaml, deep-merges the gitignored private overlay, and exposes
the few derived values documents actually need.

Nothing else in the codebase is allowed to invent a fact. If a sentence in a
generated letter contains a name, a number, or a date, it came through here.
"""

from __future__ import annotations

import datetime as _dt
import os
import re
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

import yaml

#: Sentinel for a value the owner still has to supply.
ASK = "ASK"

_MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
_SEASONS = {
    (1, 2, 3, 4, 5): "spring",
    (6, 7, 8): "summer",
    (9, 10, 11, 12): "fall",
}


def _season(month: int) -> str:
    for months, name in _SEASONS.items():
        if month in months:
            return name
    return ""


def data_dir() -> Path:
    """Where profile.yaml and apply.db live. Overridable for tests."""
    env = os.environ.get("APPLY_DATA_DIR")
    if env:
        return Path(env).expanduser()
    return Path(__file__).resolve().parents[2] / "data"


def deep_merge(base: dict, overlay: dict) -> dict:
    """Overlay wins. Dicts merge recursively; every other type is replaced whole."""
    out = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _walk_ask(node: Any, path: str = "") -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            found += _walk_ask(v, f"{path}.{k}" if path else str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            found += _walk_ask(v, f"{path}[{i}]")
    elif isinstance(node, str) and node.strip() == ASK:
        found.append(path)
    return found


class ProfileError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class Project:
    key: str
    name: str
    tracks: list[str]
    one_line: str        #: a whole sentence — paragraph 3 of a letter prints it
    three_line: str      #: the proof paragraph's operational detail
    resume_line: str = ""  #: a clause — the resume prints it after the bold name
    technical: str = ""
    stack: tuple[str, ...] = ()
    url: str | None = None


class Profile:
    """A loaded, merged profile. Read-only."""

    def __init__(self, raw: dict, sources: list[Path]):
        self.raw = raw
        self.sources = sources

    # ---------- loading ----------

    @classmethod
    def load(cls, directory: Path | None = None) -> "Profile":
        directory = directory or data_dir()
        public = directory / "profile.yaml"
        private = directory / "profile.private.yaml"
        if not public.exists():
            raise ProfileError(
                f"no profile at {public}. Run `apply init` to scaffold one."
            )
        sources = [public]
        raw = yaml.safe_load(public.read_text()) or {}
        if private.exists():
            raw = deep_merge(raw, yaml.safe_load(private.read_text()) or {})
            sources.append(private)
        return cls(raw, sources)

    # ---------- unresolved facts ----------

    def unresolved(self) -> list[str]:
        """Dotted paths still holding the literal ASK."""
        return sorted(_walk_ask(self.raw))

    def require_resolved(self, *paths: str) -> None:
        missing = [p for p in self.unresolved() if any(p.startswith(w) for w in paths)]
        if missing:
            raise ProfileError(
                "these profile values are still ASK and cannot go into a document: "
                + ", ".join(missing)
            )

    # ---------- identity ----------

    @property
    def identity(self) -> dict:
        return self.raw.get("identity", {})

    @property
    def legal_name(self) -> str:
        return f"{self.identity.get('legal_first', '')} {self.identity.get('legal_last', '')}".strip()

    @property
    def display_name(self) -> str:
        """Preferred first name + legal last. What goes on the letterhead."""
        first = self.identity.get("preferred_name") or self.identity.get("legal_first", "")
        return f"{first} {self.identity.get('legal_last', '')}".strip()

    @property
    def file_name(self) -> str:
        """Underscored form for PDF filenames: AJ_Upadhyaya."""
        return re.sub(r"\s+", "_", self.display_name)

    @property
    def email(self) -> str:
        return self.identity.get("email", "")

    @property
    def phone(self) -> str | None:
        v = self.identity.get("phone")
        return None if v in (None, ASK) else str(v)

    @property
    def location_line(self) -> str:
        loc = self.identity.get("location", {}) or {}
        bits = [loc.get("city"), loc.get("state")]
        return ", ".join(b for b in bits if b)

    @property
    def links(self) -> dict:
        return self.raw.get("links", {}) or {}

    # ---------- education ----------

    @property
    def education(self) -> list[dict]:
        return self.raw.get("education", []) or []

    @cached_property
    def current_education(self) -> dict:
        for e in self.education:
            if e.get("current"):
                return e
        return self.education[0] if self.education else {}

    @property
    def school(self) -> str:
        return self.current_education.get("institution", "")

    @property
    def gpa(self) -> str | None:
        v = (self.raw.get("education_private") or {}).get("gpa")
        return None if v in (None, ASK) else str(v)

    @cached_property
    def grad_expected(self) -> tuple[int, int]:
        """(year, month) from the authoritative grad_expected field."""
        raw = self.current_education.get("grad_expected")
        if raw is None:
            raise ProfileError("education.grad_expected is missing; it is authoritative")
        if isinstance(raw, _dt.date):
            return raw.year, raw.month
        m = re.match(r"^(\d{4})-(\d{1,2})", str(raw))
        if not m:
            raise ProfileError(f"cannot read grad_expected {raw!r}; expected YYYY-MM")
        return int(m.group(1)), int(m.group(2))

    @property
    def grad_month_year(self) -> str:
        """'May 2027'."""
        year, month = self.grad_expected
        return f"{_MONTHS[month - 1]} {year}"

    @property
    def grad_season_year(self) -> str:
        """'spring 2027'."""
        year, month = self.grad_expected
        return f"{_season(month)} {year}"

    @property
    def grad_year(self) -> int:
        return self.grad_expected[0]

    def years_to_graduation(self, today: _dt.date | None = None) -> float:
        """How far off graduation is, in years. Negative once it has passed."""
        today = today or _dt.date.today()
        year, month = self.grad_expected
        return ((year - today.year) * 12 + (month - today.month)) / 12.0

    @property
    def class_standing(self) -> str:
        """freshman | sophomore | junior | senior | graduated, as of today.

        Derived from the graduation date rather than stored, because the stored
        version is wrong within a year and nobody remembers to update it.
        """
        return self.standing_on()

    def standing_on(self, today: _dt.date | None = None) -> str:
        """Class standing on a given date. Tests pin the date, so the suite does
        not start failing the day the profile's owner graduates."""
        left = self.years_to_graduation(today)
        if left <= 0:
            return "graduated"
        if left <= 1:
            return "senior"
        if left <= 2:
            return "junior"
        if left <= 3:
            return "sophomore"
        return "freshman"

    # ---------- experience and projects ----------

    @property
    def experience(self) -> list[dict]:
        return self.raw.get("experience", []) or []

    @cached_property
    def projects(self) -> dict[str, Project]:
        out: dict[str, Project] = {}
        for key, p in (self.raw.get("projects") or {}).items():
            out[key] = Project(
                key=key,
                name=p.get("name", key),
                tracks=list(p.get("tracks") or []),
                one_line=(p.get("one_line") or "").strip(),
                three_line=(p.get("three_line") or "").strip(),
                resume_line=re.sub(r"\s+", " ", (p.get("resume_line") or "").strip()),
                technical=(p.get("technical") or "").strip(),
                stack=tuple(p.get("stack") or ()),
                url=p.get("url"),
            )
        return out

    def projects_for(self, track: str) -> list[Project]:
        """Projects this track is allowed to cite, in profile order."""
        return [p for p in self.projects.values() if track in p.tracks]

    # ---------- authorization ----------

    @property
    def authorization(self) -> dict:
        return self.raw.get("authorization", {}) or {}

    @property
    def work_authorized(self) -> bool:
        return bool(self.authorization.get("us_work_authorized"))

    @property
    def needs_sponsorship_ever(self) -> bool:
        a = self.authorization
        return bool(a.get("requires_sponsorship_now") or a.get("requires_sponsorship_future"))

    @property
    def search_preferences(self) -> dict:
        """The `search:` block plus anything derived rather than stored.

        Class standing is derived on purpose: a stored value is wrong within a
        year, and nobody remembers to update it.
        """
        return {"class_standing": self.class_standing,
                **(self.raw.get("search") or {})}

    @property
    def essays(self) -> dict:
        return self.raw.get("essays", {}) or {}

    # ---------- the hallucination guard's allow-list ----------

    @cached_property
    def sourced_tokens(self) -> set[str]:
        """Every number-bearing token that appears anywhere in the profile, plus
        the rendered forms of the graduation date. generate.lint() will refuse a
        letter containing a digit-bearing token outside this set (unioned with
        the posting's own text)."""
        tokens: set[str] = set()

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                for v in node.values():
                    walk(v)
            elif isinstance(node, list):
                for v in node:
                    walk(v)
            elif node is not None:
                tokens.update(_digit_tokens(str(node)))

        walk(self.raw)
        year, month = self.grad_expected
        for form in (
            self.grad_month_year,
            self.grad_season_year,
            str(year),
            f"{month:02d}/{year}",
            f"{_MONTHS[month - 1][:3]} {year}",
        ):
            tokens.update(_digit_tokens(form))
        return tokens


_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9./,%$+-]*")


def _digit_tokens(text: str) -> set[str]:
    """Tokens containing at least one digit, normalised for comparison."""
    out = set()
    for tok in _TOKEN.findall(text):
        if any(c.isdigit() for c in tok):
            out.add(tok.strip(".,").lower())
    return out
