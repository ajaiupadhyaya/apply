"""Things that only break on someone else's machine."""

from __future__ import annotations

import os
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


def test_no_date_format_drops_its_padding_the_posix_way():
    """`%-d` is glibc and BSD only; Windows' strftime raises "Invalid format string"."""
    files = [*(ROOT / "src").rglob("*.py"), *(ROOT / "templates").rglob("*.html"),
             *(ROOT / "templates").rglob("*.j2")]
    hits = [f"{p.relative_to(ROOT)}:{n}" for p in files
            for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
            if "strftime" in line and re.search(r"%-[a-zA-Z]", line)]
    assert hits == []


def test_yaml_with_typography_round_trips(tmp_path):
    from apply.setup import write_profile

    data = {"note": "It’s the desk — not the title — that “matters”."}
    path = write_profile(data, tmp_path / "p.yaml")
    assert "— not the title —" in path.read_text(encoding="utf-8")


def test_install_scripts_exist_and_end_in_setup():
    ps1 = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
    sh = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    for script in (ps1, sh):
        assert "uv sync" in script and "apply setup" in script
    assert "winget install" in ps1 and "MiKTeX.MiKTeX" in ps1 and "AutoInstall=1" in ps1
    assert "astral.sh/uv/install.ps1" in ps1


def test_install_scripts_are_ascii_shebanged_and_executable():
    ps1 = ROOT / "scripts" / "install.ps1"
    sh = ROOT / "scripts" / "install.sh"
    assert ps1.read_bytes().isascii()
    assert sh.read_text(encoding="utf-8").startswith("#!/usr/bin/env bash")
    if os.name != "nt":
        assert os.access(sh, os.X_OK)


def test_install_scripts_verify_each_step():
    ps1 = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
    sh = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    assert "uv sync failed" in ps1 and "$LASTEXITCODE" in ps1
    assert "uv installed but not found" in ps1
    assert "https://miktex.org/download" in ps1
    assert "MiKTeX is not on PATH yet" in ps1
    assert "uv run apply status" in ps1
    assert "uv installed but not on PATH" in sh
    # uv sync runs before the TeX check, so the hint prints after it
    assert sh.index("uv sync") < sh.index("command -v pdflatex")


def test_cli_makes_a_cp1252_stdout_utf8(monkeypatch):
    import io
    import sys
    from apply import cli
    raw = io.BytesIO()
    fake = io.TextIOWrapper(raw, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", fake)
    cli._utf8_streams()
    cli.console.print("✓ —")
    fake.flush()
    assert "✓ —".encode("utf-8") in raw.getvalue()


def test_docs_point_new_users_at_setup_on_every_os():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "## Start here" in readme
    assert "scripts\\install.ps1" in readme and "scripts/install.sh" in readme
    assert "Windows" in readme and "Task Scheduler" in readme
    assert "apply setup" in agents and "uv run" in agents and "Never" in agents
