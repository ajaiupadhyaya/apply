"""Write tests/fixtures/score_corpus.local.json: what the gate says about a real
pipeline, on the one machine that has one.

This file is gitignored, and everything this tool writes goes into it. It used
to write a second, committed corpus as well — the same rows with the firms'
names cut out — and that was the corpus the suite asserted against. It is not
any more. Cutting names out is a denylist: the registry's spellings go, and the
sub-brand, the product name and the office address stay, and any one of them
names the firm. In a corpus whose employer column groups rows, one survivor
names every other row of that employer with it. The committed corpus is
tests/fixtures/gate_corpus.json now, synthesised from the gate's own vocabulary
by tools/synthesize_corpus.py, with nothing in it that needs keeping out.

What is left for this one is the half a synthesis cannot do: real titles as
employers write them, real locations as job boards write them, and the rules
that only fire on a description. `test_search_config.py` replays it when it is
there and skips itself when it is not, so it is the owner's re-verification and
nobody else's problem.

  titles   every posting, scored on title, location and priority alone
  bodied   a sample, scored with the first 2400 characters of the description

Both are scored exactly as stored, against the vocabulary the package ships
rather than against this machine's data/search.yaml — the test replays them
that way, and a corpus frozen against one configuration and replayed against
another is not frozen at all.

The names still come out. Not because this file is published — it is not — but
because a corpus is easier to read when it is about the scorer, and because a
file one command away from being pasted into a bug report should not be a
target list:

  - the employer label is a keyed hash, and the key is random per run and never
    written down, so the label groups rows that share an employer and says
    nothing else. A plain digest of the name would not: the population of firms
    is small and public, so an unsalted hash is a guessing game, not a secret.
  - every registry name and alias, and the row's own employer, is cut out of
    the title and the location before either is scored.

Cutting a name out must not move a verdict — a firm's name is not supposed to
be part of what the gate reads. If one moves, the gate is scoring something it
should not, so this script reports every move and writes nothing. Pass
--allow-moves once you have looked at the list and know why it is there.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import sys
from pathlib import Path

from apply import search
from apply.discover import load_employers
from apply.profile import Profile, data_dir
from apply.score import score
from apply.sources.base import RawPosting

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "tests" / "fixtures" / "score_corpus.local.json"
TRIM = 2400
SAMPLE = 150

#: The vocabulary the package ships, which is what the test replays against. A
#: bare `score(posting)` would read this machine's data/search.yaml instead, and
#: a corpus frozen through one person's overrides cannot be reproduced without
#: them.
SHIPPED = search.load(Path("/nonexistent"))

#: Random per run and never stored, so the employer labels cannot be turned
#: back into a target list by hashing a list of candidate firms.
KEY = secrets.token_bytes(32)


def anonymise(name: str) -> str:
    digest = hmac.new(KEY, (name or "").encode(), hashlib.sha256).hexdigest()
    return "Firm " + digest[:6].upper()


def spellings(employers: list[dict]) -> list[str]:
    """Every name the registry knows a firm by, longest first.

    Longest first so that "Fenwold Securities" is taken out whole rather than
    leaving "Securities" behind when the alias "Fenwold" matches.
    """
    names = set()
    for entry in employers:
        names.add(entry.get("name") or "")
        names.update(entry.get("aliases") or [])
    return sorted({n.strip() for n in names if len(n.strip()) > 1},
                  key=len, reverse=True)


def _letters(text: str) -> tuple[str, list[int]]:
    """The text's alphanumerics, lowercased, and where each one came from."""
    kept, index = [], []
    for position, char in enumerate(text):
        if char.isalnum():
            kept.append(char.lower())
            index.append(position)
    return "".join(kept), index


def _cut_name(title: str, name: str) -> str:
    """Remove one firm's name from a title however that title punctuates it.

    A registry entry says "BTWrenfield"; a posting writes "B.T. Wrenfield".
    Matching on the letters alone catches both — and both are the same
    disclosure. The match still has to begin and end at a word boundary in the
    original text, so "Gram" cannot be cut out of "Programme".
    """
    needle, _ = _letters(name)
    if len(needle) < 2:
        return title
    while True:
        haystack, index = _letters(title)
        found = -1
        start = haystack.find(needle)
        while start != -1:
            first, last = index[start], index[start + len(needle) - 1]
            before = title[first - 1] if first else ""
            after = title[last + 1] if last + 1 < len(title) else ""
            if not before.isalnum() and not after.isalnum():
                found = start
                break
            start = haystack.find(needle, start + 1)
        if found == -1:
            return title
        first, last = index[found], index[found + len(needle) - 1]
        title = title[:first] + " " + title[last + 1:]


def scrub(text: str, names: list[str]) -> str:
    """The text with every given firm name cut out, and the gaps closed up."""
    text = text or ""
    for name in names:
        text = _cut_name(text, name)
    text = re.sub(r"\s+'s\b", "", text)                  # "<Firm>'s Analyst Program"
    text = re.sub(r"\(\s*\)|\[\s*\]", " ", text)         # "(<Firm>)"
    text = re.sub(r"\s+([,;:.)\]])", r"\1", text)
    text = re.sub(r"([(\[])\s+", r"\1", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -–—|,:;/&·").strip()


def posting_of(employer: str, title: str, location: str, priority: int,
               body: str) -> RawPosting:
    return RawPosting(employer=employer, title=title, url="", source="frozen",
                      location=location, description=body,
                      employer_priority=priority)


def as_stored(row, names: list[str]) -> tuple[str, str, str]:
    """The employer, title and location a frozen row is allowed to carry.

    A Workday location is an office, and an office can be as good as a name: a
    board that writes "<FIRM> PLACE ... 200 <STREET>" has put the firm's address
    where the city should be. So the same cut is made in both strings.
    """
    known = [*names, row["company"] or ""]
    return (anonymise(row["company"]), scrub(row["role"], known),
            scrub(row["location"], known))


def row_to_case(row, preferences, body: str, names: list[str]) -> dict:
    """One frozen case, scored on exactly the strings it stores."""
    employer, title, location = as_stored(row, names)
    priority = row["priority"] or 3
    verdict = score(posting_of(employer, title, location, priority, body),
                    preferences, config=SHIPPED)
    return {
        "employer": employer, "title": title,
        "location": location, "priority": priority,
        "body": body, "value": verdict.value, "verdict": verdict.verdict.value,
        "rejected_by": verdict.rejected_by,
    }


def moved_by_scrubbing(rows, preferences, names: list[str]) -> list[str]:
    """Rows whose verdict depends on a firm's name being in what it scores."""
    moves = []
    for row in rows:
        priority = row["priority"] or 3
        before = score(posting_of(row["company"], row["role"] or "",
                                  row["location"], priority, ""), preferences,
                       config=SHIPPED)
        employer, title, location = as_stored(row, names)
        after = score(posting_of(employer, title, location, priority, ""),
                      preferences, config=SHIPPED)
        if (before.value, before.verdict, before.rejected_by) != (
                after.value, after.verdict, after.rejected_by):
            moves.append(
                f"{(row['role'] or '')[:56]!r} -> {title[:56]!r}: "
                f"{before.verdict.value} {before.value} "
                f"({before.rejected_by}) -> {after.verdict.value} {after.value} "
                f"({after.rejected_by})")
    return moves


def main() -> None:
    preferences = Profile.load().search_preferences
    names = spellings(load_employers())
    conn = sqlite3.connect(f"file:{data_dir() / 'apply.db'}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT company, role, location, jd_raw, priority FROM posting ORDER BY slug"
    ).fetchall()

    moves = moved_by_scrubbing(rows, preferences, names)
    if moves:
        print(f"{len(moves)} verdicts move when the firm's name leaves the row:")
        for line in moves[:20]:
            print("  " + line)
        if "--allow-moves" not in sys.argv:
            print("\nNothing written. The gate is reading the employer's name out of "
                  "the title or the location; work out why, then rerun with "
                  "--allow-moves.")
            raise SystemExit(1)

    titles = [row_to_case(row, preferences, "", names) for row in rows]
    step = max(1, len(rows) // SAMPLE)
    bodied = [row_to_case(row, preferences, (row["jd_raw"] or "")[:TRIM], names)
              for row in rows[::step]][:SAMPLE]

    head = {"graduation": list(preferences["graduation"]),
            "class_standing": preferences["class_standing"]}
    OUT.write_text(json.dumps({**head, "titles": titles, "bodied": bodied}, indent=1))
    print(f"{len(titles)} titles and {len(bodied)} with bodies -> {OUT} "
          f"({OUT.stat().st_size // 1024} KB, gitignored)")
    print("The committed corpus is tests/fixtures/gate_corpus.json; write that "
          "with tools/synthesize_corpus.py.")


if __name__ == "__main__":
    main()
