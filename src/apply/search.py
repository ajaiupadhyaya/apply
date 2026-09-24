"""What the gate is looking for, as data rather than as literals.

The algorithm in score.py is general: reject on these patterns, weight a title
against those, add for a place. The vocabulary was specific — one person's
city, field and graduating year, written into the source. It lives here now:
defaults shipped with the package in search.defaults.yaml, overridden a block
at a time by data/search.yaml.

An override replaces a block whole rather than merging into it, because half a
list of rejects is a worse thing to reason about than either the default list
or your own. `apply search` prints which blocks are yours.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

DEFAULTS = Path(__file__).resolve().parent / "search.defaults.yaml"

#: A pattern that matches nothing, for a block someone emptied out.
_NEVER = re.compile(r"(?!x)x")


def _any(patterns: list[str], block: str = "") -> re.Pattern:
    """Whole-token alternation, the form score.py has always used.

    `block` only ever appears in an error message, and it is the difference
    between "bad escape" and knowing which line of your YAML to go and fix.
    """
    if isinstance(patterns, str) or not isinstance(patterns, (list, tuple)):
        raise TypeError(f"search config: {block} must be a list of patterns, "
                        f"got {patterns!r}")
    if not patterns:
        return _NEVER
    try:
        return re.compile(
            "|".join(rf"(?<![A-Za-z0-9]){p}(?![A-Za-z0-9])" for p in patterns), re.I)
    except re.error as exc:
        raise ValueError(f"search config: {block} has a pattern re cannot "
                         f"compile ({exc})") from exc


@dataclass(frozen=True, slots=True)
class SearchConfig:
    rejects: dict[str, re.Pattern]
    class_scoped: dict[str, re.Pattern]
    #: key, label, weight, pattern, and whether the title counts as well.
    geography: tuple[tuple[str, str, int, re.Pattern, bool], ...]
    non_us: re.Pattern
    role_fit: tuple[tuple[str, int], ...]
    timing: tuple[tuple[str, int], ...]
    title_timing: tuple[tuple[str, int], ...]
    thresholds: dict[str, int]
    #: The country whose addresses the gate may assume it knows. See the
    #: `country` block in search.defaults.yaml.
    country: str
    #: block name → "defaults", or the override file that supplied it.
    sources: dict[str, str]
    #: block name → how many entries it holds, for `apply search` to print.
    sizes: dict[str, int]

    @property
    def assume_us(self) -> bool:
        """Whether US state names may stand in for a geography match."""
        return self.country.strip().lower() in ("us", "usa", "united states")


def _merge(base: dict, override: dict) -> tuple[dict, dict[str, str]]:
    merged = dict(base)
    sources = {key: "defaults" for key in base}
    for key, value in (override or {}).items():
        merged[key] = value
        sources[key] = "data/search.yaml"
    return merged, sources


def _weighted(rows, block: str) -> tuple[tuple[str, int], ...]:
    out = []
    for row in rows or []:
        try:
            pattern, weight = row
            re.compile(pattern)
        except (TypeError, ValueError, re.error) as exc:
            raise ValueError(f"search config: {block} wants [pattern, weight] "
                             f"pairs, got {row!r} ({exc})") from exc
        out.append((pattern, int(weight)))
    return tuple(out)


def _size(block) -> int:
    """How many entries a block holds, counted the way the YAML writes them."""
    if isinstance(block, dict):
        return sum(len(v) if isinstance(v, list) else 1 for v in block.values())
    return len(block or [])


def build(raw: dict, sources: dict[str, str]) -> SearchConfig:
    """Compile a loaded mapping. Raises if a block is the wrong shape."""
    geography = []
    for key, block in (raw.get("geography") or {}).items():
        where = sources.get("geography", "defaults")
        try:
            patterns, weight = block["patterns"], int(block["weight"])
        except (KeyError, TypeError, ValueError) as exc:
            raise KeyError(f"search config: geography.{key} needs `weight` and "
                           f"`patterns` ({where}): {exc}") from exc
        geography.append((key, str(block.get("label", key)), weight,
                          _any(patterns, f"geography.{key}"),
                          bool(block.get("match_title"))))
    return SearchConfig(
        rejects={name: _any(patterns, f"rejects.{name}")
                 for name, patterns in (raw.get("rejects") or {}).items()},
        class_scoped={year: _any(patterns, f"class_scoped.{year}")
                      for year, patterns in (raw.get("class_scoped") or {}).items()},
        geography=tuple(geography),
        non_us=_any(raw.get("non_us") or [], "non_us"),
        role_fit=_weighted(raw.get("role_fit"), "role_fit"),
        timing=_weighted(raw.get("timing"), "timing"),
        title_timing=_weighted(raw.get("title_timing"), "title_timing"),
        thresholds={**{"pursue": 70, "maybe": 45}, **(raw.get("thresholds") or {})},
        country=str(raw.get("country") or "us"),
        sources=sources,
        sizes={name: _size(block) for name, block in raw.items()},
    )


@lru_cache(maxsize=8)
def _load_cached(path: str | None) -> SearchConfig:
    raw = yaml.safe_load(DEFAULTS.read_text()) or {}
    override: dict = {}
    if path and Path(path).exists():
        override = yaml.safe_load(Path(path).read_text()) or {}
    merged, sources = _merge(raw, override)
    return build(merged, sources)


# ------------------------------------------------- a starter for one person
#
# `apply setup` asks where you want to work and then has to do something with
# the answer. Shipping it into the profile alone would be a lie: the profile is
# read by the letter, and it is this file that decides what the gate pays for.
# So the answer is written here, as the one block that has to be someone's own.


def _pattern_for(place: str) -> str:
    """A city as a regex the gate can match: 'New York' → `New\\s+York`.

    Whitespace between the words becomes `\\s+`, because job boards write the
    same city a dozen ways — "NY-New York", "New  York", "New York City". Each
    word is escaped on its own, because a city with a '.' in it is not a
    wildcard: "St. Louis" has to come out as `St\\.\\s+Louis`.

    The escaping happens per word rather than to the whole string on purpose.
    `re.escape` escapes a space as `\\ `, so escaping first and substituting
    afterwards turns the separator into a literal backslash followed by `s+` —
    a pattern that matches "New\\sssYork" and never matches "New York". Every
    two-word city `apply setup` was given used to be written into the gate that
    way, so the block scored nothing and the user saw only the consolation
    prizes underneath it.
    """
    return r"\s+".join(re.escape(word) for word in place.split())


def country_of(city: str) -> str:
    """'us', 'elsewhere', or '' when the answer does not say which.

    The evidence is the string the user typed and nothing else. A US state on
    the end of it, or a city the shipped `geography` blocks already name, is the
    United States; a city the shipped `non_us` list already names is not. A bare
    "Berlin" says neither, and guessing at it is how a stranger ends up running
    someone else's country as if it were their own.
    """
    from .parse import _STATE_ALT

    city = (city or "").strip()
    if not city:
        return ""
    raw = yaml.safe_load(DEFAULTS.read_text()) or {}
    if _any(raw.get("non_us") or [], "non_us").search(city):
        return "elsewhere"
    if re.search(rf",\s*(?:{_STATE_ALT})\.?\s*$", city, re.I):
        return "us"
    for key, block in (raw.get("geography") or {}).items():
        if key != "remote" and _any(block.get("patterns") or [], key).search(city):
            return "us"
    return ""


def starter(city: str, work: str = "") -> str:
    """A data/search.yaml for one person, from the city they gave `apply setup`.

    Two blocks and nothing else. `geography` because the shipped one is a list
    of one person's cities and is wrong for everybody else, and `country` — with
    an emptied `non_us` — whenever the city is not American, because the rest of
    the shipped geography is US knowledge that would otherwise refuse the user's
    own continent for free and without saying so.

    Everything the gate looks for beyond a place is left to the defaults on
    purpose: a sentence about the work you want is not a regular expression, and
    inventing one from it would put words in the gate's mouth that the user
    never said. `apply search` prints what is in force.
    """
    city = (city or "").strip()
    country = country_of(city)
    lines = [
        "# The relevance gate, as far as it is yours.",
        "#",
        "# `apply setup` wrote this from the city you gave it. Every block the",
        "# package ships is listed by `apply search`; copy any of them here to",
        "# take it over, and a block you leave out keeps the shipped value. An",
        "# override replaces its block whole rather than merging into it.",
    ]
    if work:
        lines += ["#",
                  f"# The work you said you were after: {work}. That shapes the",
                  "# `role_fit` block, which is still the shipped one — read it with",
                  "# `apply search` and edit it here if it is looking for the wrong",
                  "# job. It is left alone because a sentence is not a pattern."]
    lines.append("")

    if not city:
        lines += [
            "# You did not say where you want to work, so the shipped geography is",
            "# still in force — one person's cities, and probably not yours. Fill",
            "# this in: `patterns` are regular expressions matched against a",
            "# posting's location, and the first block that matches is the one",
            "# that scores.",
            "#",
            "# geography:",
            "#   primary: {weight: 25, label: Your City, patterns: ['your\\s+city']}",
        ]
        return "\n".join(lines) + "\n"

    patterns = [_pattern_for(city)]
    head, _, tail = city.partition(",")
    if tail.strip():
        # "New York, NY" is two ways of saying it, and a board will write either.
        # Each pattern gets its own word boundaries when the block is compiled.
        patterns = [_pattern_for(head), _pattern_for(tail)]
    lines += [
        f"# Where you said you want to work: {city}. The first block that matches",
        "# a posting's location is the one that scores, so `primary` is the goal",
        "# and everything after it is a consolation prize. Add your own: a second",
        "# city, the place you already live, a region you would move to.",
        "geography:",
        f"  primary: {{weight: 25, label: {_label(head or city)}, "
        f"patterns: [{', '.join(_quote(p) for p in patterns)}]}}",
        "  remote: {weight: 10, label: remote, match_title: true, patterns: [",
        "    'remote', 'work\\s+from\\s+home', 'virtual', 'anywhere']}",
    ]
    if country == "us":
        lines += [
            "  hub: {weight: 6, label: US finance hub, patterns: [",
            "    'boston', 'chicago', 'san\\s+francisco', 'stamford', 'greenwich',",
            "    'jersey\\s+city', 'philadelphia', 'charlotte', 'atlanta', 'dallas',",
            "    'houston', 'los\\s+angeles', 'miami', 'austin', 'seattle', 'denver']}",
        ]
        return "\n".join(lines) + "\n"

    why = (f"# {city} is not in the United States, so the two checks that are"
           if country == "elsewhere" else
           f"# Nothing about {city} says which country it is in, so the two checks that are")
    lines += [
        "",
        why,
        "# US knowledge are switched off here: `non_us`, a list of cities the",
        "# shipped search treats as somewhere else — London and Toronto are on",
        "# it — and the state-name check that lets 'Boise, Idaho' through with no",
        "# `geography` match at all. With both quiet, a posting somewhere you",
        "# have not named scores no place bonus rather than being refused for",
        "# free and without saying so. List the places you would genuinely",
        "# refuse in `non_us` and that half starts working again, for you.",
        "country: elsewhere",
        "non_us: []",
    ]
    return "\n".join(lines) + "\n"


def _label(city: str) -> str:
    """A YAML-safe label. Plain scalars are fine until a ':' or a '#' shows up."""
    city = city.strip()
    return f'"{city}"' if re.search(r"[:#{}\[\],&*?|<>=!%@`\"']", city) else city


def _quote(pattern: str) -> str:
    return "'" + pattern.replace("'", "''") + "'"


def load(data: Path | None = None) -> SearchConfig:
    """The configuration in force. `data` defaults to the profile's data dir.

    Cached per path for the life of the process, which is the life of one CLI
    command. A long-running `apply serve` needs a restart to see an edit.
    """
    if data is None:
        from .profile import data_dir

        data = data_dir()
    return _load_cached(str(Path(data) / "search.yaml"))
