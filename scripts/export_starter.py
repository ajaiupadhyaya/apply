"""Build the starter repo: every tracked file, none of the author's life.

    uv run python scripts/export_starter.py <target-dir>

Authorship stays (the LICENSE, the repository URL); biography does not. The
check is the same word list tests/test_setup.py holds the persona to, run over
every file that ships. Binary (non-UTF-8) files are not scanned; they are listed
on stderr as skipped.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

EXCLUDE_PREFIXES = ("docs/superpowers/", ".reviews/")
#: Owner-only tooling: it holds the owner's identifiers as literals, so it never ships.
EXCLUDE_FILES = ("scripts/export_starter.py", "tests/test_export.py")
#: Identifiers that embed the owner's name (email local parts, username, home
#: path, handle-prefixed tokens): matched as substrings, so "ajaiupad@..." hits.
COMPOUND = ("ajai", "upadhyaya", "ajaiupad", "upadhyayaak", "ajaiupadhyaya", "ohcamel")
#: Ordinary words and phrases: matched on word boundaries ("wrds" inside a word is fine).
WORDS = ("vcu", "virginia commonwealth", "university of virginia", "richmond",
         "charlottesville", "bloomberg", "morningstar", "wrds")
BIOGRAPHY = COMPOUND + WORDS
_PATTERN = re.compile("|".join([*map(re.escape, COMPOUND),
                                *(rf"\b{re.escape(w)}\b" for w in WORDS)]))
#: The only strings that may name the author: attribution, not biography. Each
#: is removed from a line before it is scanned, so anything else on the line
#: (an email after a namespace, "VCU" after a copyright) is still flagged.
ALLOWED_STRINGS = ("Copyright (c) 2026 Ajai Upadhyaya",
                   "@namespace https://github.com/ajaiupadhyaya",
                   "github.com/ajaiupadhyaya/apply",
                   "com.ajaiupadhyaya.apply")


def biography_in(paths: Iterable[Path], skipped: list[Path] | None = None) -> list[str]:
    """Hits as "path:line". Only UTF-8 text is scanned; binary files are not,
    and are appended to `skipped` when a list is given."""
    hits = []
    for path in paths:
        if path.name in ("test_setup.py",):
            continue                       # holds the older AUTHORS_BIOGRAPHY list, and ships
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            if skipped is not None:
                skipped.append(path)
            continue
        for n, line in enumerate(text.splitlines(), 1):
            line = " ".join(line.split())     # userscript headers align with runs of spaces
            for ok in ALLOWED_STRINGS:
                line = line.replace(ok, "")
            if _PATTERN.search(line.lower()):
                hits.append(f"{path}:{n}")
    return hits


def export(target: Path, repo: Path) -> list[str]:
    if target.exists() and any(target.iterdir()):
        raise SystemExit(f"{target} is not empty")
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=repo, capture_output=True, check=True)
    names = [n for n in listed.stdout.decode("utf-8").split("\0")
             if n and not n.startswith(EXCLUDE_PREFIXES) and n not in EXCLUDE_FILES]
    skipped: list[Path] = []
    hits = biography_in((repo / n for n in names), skipped)
    for path in skipped:
        print(f"not scanned (not UTF-8 text): {path.relative_to(repo)}", file=sys.stderr)
    if hits:
        raise SystemExit("the author's biography is in files that would ship:\n  " + "\n  ".join(hits))
    for name in names:
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(repo / name, dest)
    git = ["git", "-c", "user.name=APPLY", "-c", "user.email=apply@localhost"]
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=target, check=True)
    subprocess.run(["git", "add", "-A"], cwd=target, check=True)
    subprocess.run([*git, "commit", "-q", "-m", "APPLY starter"], cwd=target, check=True)
    return names


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("usage: export_starter.py <target-dir>")
    out = export(Path(sys.argv[1]).resolve(), Path(__file__).resolve().parents[1])
    print(f"exported {len(out)} files to {sys.argv[1]} as one commit.\n"
          "Publish:  cd <target> && gh repo create apply-starter --private --source . --push")
