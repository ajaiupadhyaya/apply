"""Things that only break on someone else's machine."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IO = re.compile(r"\.(read_text|write_text)\(|(?<![\w.])open\(")
SUBPROCESS_TEXT = re.compile(r"text=True")


def _offenders(paths, pattern, needle):
    out = []
    for path in paths:
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line) and needle not in line and "webbrowser" not in line:
                if re.search(r"open\([^)]*['\"][rwa]b['\"]", line):
                    continue                       # binary mode has no encoding
                out.append(f"{path.relative_to(ROOT)}:{n}: {line.strip()}")
    return out


def test_every_text_read_and_write_names_its_encoding():
    """Windows defaults to cp1252; the first em-dash in a letter would crash."""
    files = [*(ROOT / "src").rglob("*.py"), *(ROOT / "tools").rglob("*.py"),
             *(ROOT / "tests").rglob("*.py")]
    assert _offenders(files, IO, "encoding=") == []


def test_every_text_subprocess_names_its_encoding():
    assert _offenders((ROOT / "src").rglob("*.py"), SUBPROCESS_TEXT, "encoding=") == []


def test_yaml_with_typography_round_trips(tmp_path):
    from apply.setup import write_profile

    data = {"note": "It’s the desk — not the title — that “matters”."}
    path = write_profile(data, tmp_path / "p.yaml")
    assert "— not the title —" in path.read_text(encoding="utf-8")
