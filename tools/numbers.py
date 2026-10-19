"""Every figure the README quotes, recomputed from this machine.

Run it before editing the README, and paste what it prints. The point is that a
reader can run it too, against their own pipeline, and get their own numbers
rather than trusting ours.

It opens the database read-only and names no employer: a registry is a list of
where someone is applying, so only the counts leave this script.

    uv run python tools/numbers.py
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter

from apply.discover import load_employers
from apply.profile import data_dir
from apply.search import load as load_search

#: The vocabulary blocks worth a line, and what to call them in prose.
BLOCKS = {
    "rejects": "reject patterns",
    "geography": "places",
    "non_us": "non-US places",
    "role_fit": "role patterns",
    "timing": "timing patterns",
    "class_scoped": "class-year patterns",
}


def table(figures: list[tuple[str, str]]) -> str:
    width = max(len(name) for name, _ in [*figures, ("figure", "")])
    header = [f"| {'figure'.ljust(width)} | value |", f"|{'-' * (width + 2)}|---|"]
    return "\n".join([*header, *(f"| {name.ljust(width)} | {value} |"
                                 for name, value in figures)])


def tally(counts: Counter) -> str:
    return ", ".join(f"{count} {name}" for name, count in counts.most_common())


def open_readonly(path) -> sqlite3.Connection | None:
    """The author's live pipeline. Opened so that it cannot be written to."""
    if not path.exists():
        return None
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def from_config() -> list[tuple[str, str]]:
    config = load_search()
    figures = [("gate", f"pursue ≥ {config.thresholds['pursue']}, "
                f"maybe ≥ {config.thresholds['maybe']}"),
               ("vocabulary", ", ".join(f"{config.sizes[block]} {label}"
                                        for block, label in BLOCKS.items()
                                        if block in config.sizes))]
    employers = load_employers()
    if employers:
        figures.insert(0, ("registry", f"{len(employers)} firms — "
                           + tally(Counter(e.get("ats", "?") for e in employers))))
    return figures


#: A table this script reads that is not part of the schema `apply init` writes,
#: mapped to the command that creates it. Both are made on first use by the
#: module that owns them, so a database that has only ever been set up and
#: filled has neither — and this script is the first thing the README asks a
#: reader to run. It says what it cannot compute and why, rather than stopping.
MADE_ON_FIRST_USE = {
    "run": "apply run",
    "spend": "apply gen",
}


def from_database(conn: sqlite3.Connection) -> tuple[list[tuple[str, str]], list[str]]:
    """Every figure this database can support, and a note for each it cannot."""
    figures: list[tuple[str, str]] = []
    missing: list[str] = []

    for name, command in MADE_ON_FIRST_USE.items():
        if not table_exists(conn, name):
            missing.append(f"no `{name}` table yet — `{command}` creates it on its "
                           f"first run, so those rows are not here to count")

    if table_exists(conn, "posting"):
        filed, pursue, maybe, rejected = conn.execute(
            "SELECT count(*), sum(score_verdict = 'pursue'), sum(score_verdict = 'maybe'),"
            " sum(score_verdict = 'reject') FROM posting").fetchone()
        if filed:
            figures.append(("postings filed", f"{filed} — {pursue or 0} pursue, {maybe or 0} "
                            f"maybe, {rejected or 0} since screened out by a gate change"))
            figures.append(("boards they came from", tally(Counter(dict(conn.execute(
                "SELECT source, count(*) FROM posting GROUP BY source"))))))
        else:
            missing.append("no postings filed yet — `apply discover` or `apply seed`")

    if table_exists(conn, "run"):
        last = conn.execute("SELECT discovered, ingested, generated, summary FROM run"
                            " ORDER BY started_at DESC LIMIT 1").fetchone()
        if last:
            discovered, ingested, generated, summary = last
            gate = re.search(r"(\d+) fetched, (\d+) rejected", summary or "")
            figures.append(("last unattended pass",
                            (f"{gate.group(1)} fetched, {gate.group(2)} rejected for free, "
                             if gate else "")
                            + f"{discovered} filed from boards, {ingested} from alert mail, "
                            f"{generated} letters written"))

    if table_exists(conn, "application"):
        statuses = Counter(dict(conn.execute(
            "SELECT status, count(*) FROM application GROUP BY status")))
        promoted = sum(count for status, count in statuses.items()
                       if status not in ("draft", "generated"))
        if statuses.get("generated"):
            figures.append(("documents built", f"{statuses['generated']} letters generated, "
                            f"{promoted} promoted past the human gate"))

    if table_exists(conn, "spend"):
        calls, usd = conn.execute("SELECT count(*), sum(usd) FROM spend").fetchone()
        letters = conn.execute("SELECT count(DISTINCT slug) FROM spend"
                               " WHERE purpose LIKE 'write%'").fetchone()[0]
        if calls and letters:
            figures.append(("model spend", f"${usd:.2f} over {calls} calls for {letters} "
                            f"letters — ${usd / letters:.2f} a letter, audit included"))
    return figures, missing


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (name,)).fetchone())


def main() -> None:
    figures = from_config()
    missing = []
    path = data_dir() / "apply.db"
    conn = open_readonly(path)
    if conn is None:
        missing.append(f"no database at {path} — `apply setup` writes one")
    else:
        found, missing = from_database(conn)
        figures += found
        conn.close()
    print(table(figures))
    # The configuration figures above are true on a clone that has never been
    # run; the pipeline ones need a pipeline. Which is which has to be said, or
    # a short table reads as a broken tool.
    for note in missing:
        print(f"\nnot computed: {note}")


if __name__ == "__main__":
    main()
