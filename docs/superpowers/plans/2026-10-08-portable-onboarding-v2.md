# Portable APPLY (v2, on `publish-clean`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** APPLY runs fully on Windows. A new user goes from `git clone` to a
configured pipeline through `apply setup`, which imports their documents and
has Claude draft their profile, search, tracks and firms. The owner's scoring
stays byte-for-byte the same.

**Architecture:** This plan builds on the owner's `publish-clean` branch,
which already has the following:
- a fictional persona (Rae Mercer) used as both scaffold and test fixture
- YAML gate vocabulary: `search.defaults.yaml` plus a gitignored
  `data/search.yaml`
- a 9-question `apply setup`
- secrets lookup in `secrets.py`
- scheduler backends for launchd, systemd and cron
- CI on Ubuntu and macOS

On top of that, this plan does six things:
1. Adds Windows branches to the existing OS seams.
2. Moves tracks and the last hardcoded gate limits into the YAML.
3. Turns `setup.py` into a package holding a document-driven wizard.
4. Adds Windows to CI.
5. Adds bootstrap scripts and docs.
6. Adds an export script for a clean starter repo.

**Tech Stack:** Python 3.11+, uv, typer/rich, PyYAML, pydantic (via
anthropic), pypdf, httpx, `keyring` (new, owner-approved), pytest, GitHub
Actions, PowerShell.

**Spec:** `docs/superpowers/specs/2026-10-08-portable-onboarding-design.md`.
Read its **Addendum** at the bottom first: where the spec body and the
addendum differ, the addendum wins.

**Context file:**
`/private/tmp/claude-501/-Users-ajaiupadhyaya-Documents-apply/fdb3c8a0-0046-4f1a-a97a-6f06ecdbe505/scratchpad/gap-analysis.md`.
It maps this branch file:line by file:line: signatures, fixtures, and every
Windows-incompatible site. Implementers read the sections their task names.

## Global Constraints

- **Hard rules from CLAUDE.md:**
  - Never submit an application.
  - Never scrape or authenticate against Handshake.
  - Never store credentials, SSN, DOB or bank details in the repo or in any
    file.
  - Never promote to `ready` or `submitted` without a human.
  - Never write a fact into a generated document that is not in
    `profile.yaml`.
- **The repo is public.** No real person's data goes in any tracked file. The
  existing owner-string tests (`tests/test_setup.py` `AUTHORS_BIOGRAPHY`,
  `tests/test_search_config.py`) must keep passing.
- **uv for everything:** `uv run ...`, `uv add ...`. Never bare pip. The only
  new runtime dependency is `keyring`.
- **Tests:**
  - Tests never call the API. `tests/conftest.py` strips keys, stubs
    `secrets.lookup`, and trips on `llm.call`. Use `FakeClaude` or monkeypatch.
  - Every task ends with the suite green on both Pythons:
    `uv run --python 3.11 pytest -q` and `uv run --python 3.13 pytest -q`.
    The baseline is 559 passed and 1 skipped; the local owner corpus is
    present in this worktree, so expect 560 passed.
- **Behaviour preservation:** with no `data/search.yaml`, every verdict is
  unchanged. Three tests and one file pin this:
  - `tests/test_score.py`, which must stay unmodified
  - `tests/fixtures/gate_corpus.json`, verified by `tests/test_search_config.py`
  - the owner's local corpus test
    `test_the_owners_own_pipeline_still_scores_the_same`, which must keep
    passing (`tests/fixtures/score_corpus.local.json`, gitignored, present)
- **Text I/O:** every text read and write in `src/`, `tools/` and `tests/`
  passes `encoding="utf-8"`. Every `subprocess.run(..., text=True)` in `src/`
  passes `encoding="utf-8", errors="replace"`.
- **Gitignore discipline:** a new file the user writes goes into both
  `.gitignore` and `tests/test_fresh_clone.py` `USER_WRITES`, as CLAUDE.md
  requires.
- **Docs discipline:** every new CLI command must appear in README "Commands"
  (`test_every_command_in_help_is_documented_in_the_readme`).
- **Outbound requests:** any new module that sends a request must be declared
  in `src/apply/outbound.py`. Prefer putting network calls in modules already
  declared (`apply.resolve`, `apply.llm`).
- **Commits:** end every commit message with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Git hygiene:** never `git add` `tests/fixtures/score_corpus.local.json` or
  `.reviews/`. Stage files by explicit path.

## Review Focus

1. **A resume containing phone or street address.** Neither may reach
   `data/context/` or the draft request. Covered by `test_redact_*` (Task 8)
   and the full wizard run (Task 10).
2. **A pasted SSN or DOB in a free-text answer.** It is refused and the
   question is asked again. Covered by `test_free_text_refuses_ssn` (Task 10).
3. **Non-ASCII text on Windows** (em-dash, curly quotes), in YAML the wizard
   writes, in the clipboard, and in pdflatex output. Covered by Task 1's grep
   test plus round-trip test, and Task 2's clipboard decode test.
4. **Re-running `apply setup` over existing files**, including the owner's
   own and the example `employers.yaml` that `copy_examples` already wrote. It
   backs up and asks, except when the file is still byte-identical to its
   example. Covered by `test_setup_backs_up_existing_files` and
   `test_example_employers_are_replaced_silently` (Task 10).
5. **The draft blowing the $0.50 per-call cap.** The wizard raises the
   `setup` per-call cap so the draft is not refused. Covered by
   `test_request_goes_through_llm_call_and_the_ledger` (Task 9).

---

### Task 1: UTF-8 everywhere

**Files:**
- Modify: every site listed in gap-analysis §R1, "read_text / write_text /
  open( without encoding=". That is 39 sites in `src/`, 5 in `tools/` and 86
  in `tests/`. Also modify the subprocess sites listed under "Other
  subprocess `text=True` without encoding" (cli.py:113, secrets.py:50,
  schedule.py:45, generate.py:824, context.py:249).
- Create: `tests/test_portability.py`

- [ ] **Step 1: Write the failing tests**

```python
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
```

A call that spans lines (with `encoding=` on the next line) trips the grep.
Put `encoding="utf-8"` on the same line as the call.

- [ ] **Step 2: Run them to see the failures**

```bash
uv run pytest tests/test_portability.py -v
```

Expected: the two grep tests FAIL and list the sites. The round-trip test
passes on macOS; it exists for Windows CI.

- [ ] **Step 3: Fix every site**

- `x.read_text()` → `x.read_text(encoding="utf-8")`. When it already has
  `errors="replace"`, add `encoding="utf-8"` before it.
- `x.write_text(s)` → `x.write_text(s, encoding="utf-8")`.
- `subprocess.run(..., text=True)` → add `encoding="utf-8", errors="replace"`
  on the same line.
- Leave `read_bytes`/`write_bytes` alone.

- [ ] **Step 4: Run the full suite on both Pythons**

```bash
uv run --python 3.11 pytest -q && uv run --python 3.13 pytest -q
```

Expected: all pass (560 passed).

- [ ] **Step 5: Commit**

```bash
git add src tools tests/*.py
git commit -m "UTF-8 for every text read, write and subprocess, so Windows' codepage never decides

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Windows in the open, clipboard, banner and TeX seams

**Files:**
- Create: `src/apply/host.py` (only `open_path`), `tests/test_host.py`
- Modify:
  - `src/apply/cli.py`: `_open_path` delegates; `CLIPBOARD_READERS` and
    `read_clipboard` gain PowerShell; the clipboard help text
  - `src/apply/web/routes.py:292-293`: the folder route uses
    `host.open_path` on every OS
  - `src/apply/notify.py`: `banner` gets a Windows toast
  - `src/apply/generate.py:40-51`: `tex_hint` gets a Windows branch
  - `src/apply/cli.py` doctor: the MiKTeX auto-install check
- Read first: gap-analysis §1.1, §1.5 and tests/test_fresh_clone.py:314-360
  (the existing clipboard tests and how they monkeypatch `cli.shutil.which`).

**Interfaces:**
- Produces:
  - `host.open_path(path: Path) -> None`
  - `generate.miktex_autoinstall() -> bool | None`
  - `cli.read_clipboard()` keeps its signature and its `ClipboardUnavailable`
  - `notify.banner` keeps its signature

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_host.py`:

```python
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


def test_open_path_on_windows_uses_startfile(monkeypatch, tmp_path):
    from apply import host

    opened = []
    monkeypatch.setattr(host.sys, "platform", "win32")
    monkeypatch.setattr(host.os, "startfile", opened.append, raising=False)
    host.open_path(tmp_path)
    assert opened == [str(tmp_path)]


def test_open_path_on_mac_uses_open(monkeypatch, tmp_path):
    from apply import host

    calls = []
    monkeypatch.setattr(host.sys, "platform", "darwin")
    monkeypatch.setattr(host.subprocess, "run", lambda a, **k: calls.append(a))
    host.open_path(tmp_path)
    assert calls == [["open", str(tmp_path)]]


def test_windows_clipboard_is_read_through_powershell_as_utf8(monkeypatch):
    from apply import cli

    monkeypatch.setattr(cli.sys, "platform", "win32")
    monkeypatch.setattr(cli.shutil, "which", lambda n: "powershell.exe" if n == "powershell" else None)
    seen = {}

    def fake_run(argv, **kw):
        seen["argv"], seen["kw"] = argv, kw
        return subprocess.CompletedProcess(argv, 0, stdout="Analyst — Summer “2027”\r\n", stderr="")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)
    assert cli.read_clipboard() == "Analyst — Summer “2027”\n"
    assert "Get-Clipboard" in seen["argv"][-1] and "UTF8" in seen["argv"][-1]
    assert seen["kw"].get("encoding") == "utf-8"


def test_windows_banner_passes_text_through_the_environment(monkeypatch):
    from apply import notify

    seen = {}
    monkeypatch.setattr(notify.sys, "platform", "win32")
    monkeypatch.setattr(notify.shutil, "which", lambda n: "powershell.exe")
    monkeypatch.setattr(notify.subprocess, "run",
                        lambda a, **k: seen.update(argv=a, env=k["env"]) or subprocess.CompletedProcess(a, 0))
    assert notify.banner('apply "x"', "2 ready; $(rm -rf)") is True
    assert "$(rm -rf)" not in " ".join(seen["argv"])
    assert seen["env"]["APPLY_TOAST_BODY"] == "2 ready; $(rm -rf)"


def test_tex_hint_names_miktex_on_windows(monkeypatch):
    from apply import generate

    monkeypatch.setattr(generate.sys, "platform", "win32")
    assert "winget install MiKTeX.MiKTeX" in generate.tex_hint()


def test_miktex_autoinstall_reads_initexmf(monkeypatch):
    from apply import generate

    monkeypatch.setattr(generate.shutil, "which", lambda n: "initexmf" if n == "initexmf" else None)
    monkeypatch.setattr(generate.subprocess, "run",
                        lambda a, **k: subprocess.CompletedProcess(a, 0, stdout="1\n", stderr=""))
    assert generate.miktex_autoinstall() is True
    monkeypatch.setattr(generate.subprocess, "run",
                        lambda a, **k: subprocess.CompletedProcess(a, 0, stdout="2\n", stderr=""))
    assert generate.miktex_autoinstall() is False
    monkeypatch.setattr(generate.shutil, "which", lambda n: None)
    assert generate.miktex_autoinstall() is None
```

Before writing these, check that `generate`, `notify` and `cli` actually
import `sys`, `shutil` and `subprocess` at module level. Where they import
inside functions, monkeypatch the global module instead (for example
`monkeypatch.setattr("sys.platform", "win32")`) and adapt the test.

- [ ] **Step 2: Run them to see the failures**

```bash
uv run pytest tests/test_host.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement**

`src/apply/host.py`:

```python
"""Opening a file or folder the way a double-click would, on any OS.

The other platform seams live where they are used — secrets.py, schedule.py,
cli.read_clipboard, notify.banner, generate.tex_hint. This one is shared by
the CLI and the dashboard, so it has a module of its own.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import webbrowser
from pathlib import Path


def open_path(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(str(path))                              # noqa: S606 — a local path
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    elif shutil.which("xdg-open"):
        subprocess.run(["xdg-open", str(path)], check=False)
    else:
        webbrowser.open(Path(path).resolve().as_uri())
```

**`cli.py`:**
- Make `_open_path` call `host.open_path`.
- Prepend a Windows reader so it is tried first on win32. `CLIPBOARD_READERS`
  is a tuple of `(name, argv)`; add a branch to `read_clipboard` like this:

```python
#: PowerShell 5 writes to a pipe in the OEM codepage, which turns an em-dash
#: into "?". Forcing UTF-8 output is the difference between a pasted posting
#: and a mangled one.
POWERSHELL_CLIPBOARD = ("[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
                        "Get-Clipboard -Raw")
```

  In `read_clipboard`, when `sys.platform == "win32"` and
  `shutil.which("powershell")` (or `"pwsh"`) exists, run
  `[exe, "-NoProfile", "-NonInteractive", "-Command", POWERSHELL_CLIPBOARD]`
  with `capture_output=True, text=True, encoding="utf-8", errors="replace"`.
  Return `stdout.replace("\r\n", "\n")`.
- Add "PowerShell (Windows)" to the help strings that list the clipboard
  tools (cli.py:356 and :1428).

**`web/routes.py` `do_folder`:** `if directory.exists(): host.open_path(directory)`.

**`notify.banner`:** add a win32 branch before the final `return False`:

```python
    if sys.platform == "win32" and shutil.which("powershell"):
        env = {**os.environ, "APPLY_TOAST_TITLE": title[:60], "APPLY_TOAST_BODY": message[:240]}
        result = subprocess.run([shutil.which("powershell"), "-NoProfile", "-NonInteractive",
                                 "-Command", _TOAST], capture_output=True, env=env)
        return result.returncode == 0
```

with this module constant:

```python
#: The AppUserModelID Windows registers for PowerShell; a toast from an
#: unregistered ID is silently dropped on Windows 10. Title and body arrive
#: through the environment, never through the script text, so nothing in a
#: posting title can become PowerShell.
_PS_AUMID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
_TOAST = (
    "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
    "ContentType = WindowsRuntime] | Out-Null; "
    "$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
    "[Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
    "$x = $t.GetElementsByTagName('text'); "
    "$x.Item(0).AppendChild($t.CreateTextNode($env:APPLY_TOAST_TITLE)) | Out-Null; "
    "$x.Item(1).AppendChild($t.CreateTextNode($env:APPLY_TOAST_BODY)) | Out-Null; "
    f"[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('{_PS_AUMID}')"
    ".Show([Windows.UI.Notifications.ToastNotification]::new($t))"
)
```

**`generate.tex_hint`:** add a win32 branch returning

```
"winget install MiKTeX.MiKTeX   (then, in a new terminal: initexmf --set-config-value=[MPM]AutoInstall=1)"
```

Add:

```python
def miktex_autoinstall() -> bool | None:
    """Whether MiKTeX installs missing packages without asking (1 = yes).
    'Ask' opens a dialog, and a dialog hangs an unattended run. None when
    MiKTeX is not the TeX here."""
    if not shutil.which("initexmf"):
        return None
    result = subprocess.run(["initexmf", "--show-config-value=[MPM]AutoInstall"],
                            capture_output=True, text=True, encoding="utf-8", errors="replace")
    return result.stdout.strip() == "1"
```

**`cli.doctor`:** after the pdflatex check, add

```python
    if generate.miktex_autoinstall() is False:
        console.print("[yellow]•[/] MiKTeX asks before installing a package, which stalls an "
                      "unattended run:\n    initexmf --set-config-value=[MPM]AutoInstall=1")
```

- [ ] **Step 4: Run the full suite on both Pythons**

```bash
uv run --python 3.11 pytest -q && uv run --python 3.13 pytest -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/apply/host.py src/apply/cli.py src/apply/web/routes.py src/apply/notify.py src/apply/generate.py tests/test_host.py
git commit -m "Windows: open, clipboard, notifications and TeX guidance

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Writing a secret, a free key check, and the IMAP user

**Files:**
- Modify:
  - `pyproject.toml` (via `uv add keyring`)
  - `src/apply/secrets.py`
  - `src/apply/llm.py`
  - `src/apply/profile.py`
  - `src/apply/run.py:159-161`
  - `src/apply/cli.py` (ingest: `--user` default)
  - `tests/conftest.py`
  - `CLAUDE.md`
- Test: `tests/test_secrets.py`, `tests/test_llm_ping.py` (new)
- Read first:
  - gap-analysis §1.2
  - `tests/test_acceptance.py:501-560`
    (`test_no_credential_is_ever_written_to_disk`,
    `test_the_secrets_module_never_persists_what_it_reads`)

**Interfaces:**
- Produces:
  - `secrets.store(name: str, value: str) -> None`, which uses
    `keyring.set_password("apply", name, value)`. That is the same
    service/username layout `_from_keyring` already reads, so `lookup` finds
    it.
  - `secrets.platform_key()` now also returns `"windows"`.
  - `INSTRUCTIONS["windows"] = "uv run apply setup --step key"`, for
    `ANTHROPIC_API_KEY`. `how_to_store` uses
    `uv run apply setup --step extras` for `APPLY_IMAP_PASSWORD`.
  - `llm.ping() -> None`. A free `models.list(limit=1)`. Raises
    `LLMUnavailable("the API key was rejected …")` on `AuthenticationError`
    and `LLMUnavailable("could not reach the API …")` on a connection error.
  - `Profile.imap_user -> str`, from `raw["imap"]["user"]`, else `email`.

- [ ] **Step 1: Add the dependency**

```bash
uv add keyring
```

`_from_keyring` keeps its `find_spec` guard; it is harmless.

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_secrets.py`. That file already keeps the real `lookup`
reference taken at import time; follow its pattern for the new functions too.

```python
REAL_STORE = secrets.store if hasattr(secrets, "store") else None


def test_store_writes_through_keyring_under_the_layout_lookup_reads(monkeypatch):
    import keyring
    saved = {}
    monkeypatch.setattr(keyring, "set_password", lambda s, u, v: saved.update({(s, u): v}))
    secrets.store("ANTHROPIC_API_KEY", " sk-x ")
    assert saved == {("apply", "ANTHROPIC_API_KEY"): "sk-x"}


def test_store_refuses_an_empty_secret():
    import pytest
    with pytest.raises(ValueError):
        secrets.store("ANTHROPIC_API_KEY", "  ")


def test_windows_is_its_own_platform(monkeypatch):
    monkeypatch.setattr(secrets.sys, "platform", "win32")
    assert secrets.platform_key() == "windows"
    assert "apply setup --step key" in secrets.how_to_store("ANTHROPIC_API_KEY")
    assert "apply setup --step extras" in secrets.how_to_store("APPLY_IMAP_PASSWORD")
```

The autouse conftest must block real writes: in `_no_real_api`, add

```python
    monkeypatch.setattr(secrets, "store", lambda *a, **k: pytest.fail("a test tried to store a real secret"))
```

Then `REAL_STORE` (captured at import, before fixtures) is what the tests
above call. Change `secrets.store(...)` in them to `REAL_STORE(...)`.

`tests/test_llm_ping.py`:

```python
from __future__ import annotations

import pytest


def test_ping_reports_a_rejected_key(monkeypatch):
    import anthropic, httpx
    from apply import llm

    class Client:
        class models:
            @staticmethod
            def list(limit):
                req = httpx.Request("GET", "https://api.anthropic.com/v1/models")
                raise anthropic.AuthenticationError("bad", response=httpx.Response(401, request=req), body=None)

    monkeypatch.setattr(llm, "_client", lambda: Client())
    with pytest.raises(llm.LLMUnavailable, match="rejected"):
        llm.REAL_PING()


def test_ping_is_tripwired_in_tests():
    from apply import llm
    with pytest.raises(AssertionError, match="real Anthropic API"):
        llm.ping()


def test_imap_user_falls_back_to_email(profile):
    assert profile.imap_user == profile.email
    profile.raw["imap"] = {"user": "alerts@example.com"}
    assert profile.imap_user == "alerts@example.com"
```

To let a test reach the real `ping` while the tripwire is in place, keep
`REAL_PING = ping` in `llm.py` right after the definition, and have the
conftest patch only `llm.ping`. The second test then sees the tripwire.

- [ ] **Step 3: Run them to see the failures**

```bash
uv run pytest tests/test_secrets.py tests/test_llm_ping.py -v
```

Expected: FAIL.

- [ ] **Step 4: Implement**

`secrets.py`:
- Update the docstring: "Nothing here writes a secret to a file: `store`
  hands it to the OS credential store through keyring (Windows Credential
  Manager, the macOS Keychain, or a Secret Service), and no value is ever
  logged."
- Add the following:

```python
def platform_key() -> str:
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform == "win32":
        return "windows"
    return "linux" if sys.platform.startswith("linux") else "other"
```

and to `INSTRUCTIONS`:

```python
    "windows": "uv run apply setup --step {step}",
```

then in `how_to_store`:

```python
    step = "extras" if name == "APPLY_IMAP_PASSWORD" else "key"
    return INSTRUCTIONS[platform_key()].format(name=name, step=step)
```

The other entries ignore `step`, because `str.format` ignores unused keyword
arguments.

```python
def store(name: str, value: str) -> None:
    """Hand a secret to the OS credential store. Never to a file, never logged.

    Same service and username `_from_keyring` reads, so `lookup` finds it from a
    terminal and from a scheduled run alike."""
    value = (value or "").strip()
    if not value:
        raise ValueError(f"refusing to store an empty {name}")
    import keyring

    keyring.set_password("apply", name, value)
```

`test_the_secrets_module_never_persists_what_it_reads` forbids
`open`/`write*`/`mkdir`/`global` in `secrets.py`. `keyring.set_password`
trips none of them. If that test checks for a stricter phrase, read it, and
satisfy its intent: secrets never touch a file.

`llm.py`:

```python
def ping() -> None:
    """One free request that proves the key works. Raises LLMUnavailable."""
    import anthropic

    client = _client()
    try:
        client.models.list(limit=1)
    except anthropic.AuthenticationError as exc:
        raise LLMUnavailable("the API key was rejected. Check it at console.anthropic.com "
                             "and store it again: uv run apply setup --step key") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMUnavailable("could not reach the API (network).") from exc


REAL_PING = ping
```

`conftest._no_real_api`: next to the `llm.call` tripwire, add
`monkeypatch.setattr(llm, "ping", tripwire)`. The tripwire takes `**_`, so
make it `def tripwire(*_, **__)`.

`profile.py`: add the `imap_user` property after `email`.

`run.py`: `discover.fetch_imap(user=profile.imap_user, …)`.

`cli.py` ingest: `address = user or profile.imap_user`.

`CLAUDE.md`: in "Never", change the credentials line to "Store credentials,
SSN, DOB, or bank details in any file. Keys live in the environment or the OS
credential store (`secrets.store` / `secrets.lookup`)."

- [ ] **Step 5: Run the full suite on both Pythons**

```bash
uv run --python 3.11 pytest -q && uv run --python 3.13 pytest -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/apply/secrets.py src/apply/llm.py src/apply/profile.py src/apply/run.py src/apply/cli.py tests/conftest.py tests/test_secrets.py tests/test_llm_ping.py CLAUDE.md
git commit -m "Secrets can be stored (OS credential store, never a file); a free key check; IMAP user is its own key

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Task Scheduler backend

**Files:**
- Modify:
  - `src/apply/schedule.py`: add `TaskSchedulerBackend`, and a win32 branch
    in `backend()`
  - `src/apply/cli.py`: the `schedule` help text names Task Scheduler; the
    "touch data/HALT" hint becomes "create an empty file data/HALT"
  - `tests/test_fresh_clone.py:153-170`: help-text assertions now include
    Task Scheduler
- Test: `tests/test_schedule.py`
- Read first: gap-analysis §1.3, `schedule.py` entire, and `tests/test_schedule.py`
  (`_Spy`, `_run` monkeypatching).

**Interfaces:**
- Produces:
  - `TaskSchedulerBackend` with the existing backend protocol:
    `render(schedule) -> str` (task XML), `install(schedule) -> str`
    (task name), `remove() -> bool`, and `status() -> dict` with keys
    `installed, path, at, loaded, command, log`.
  - `TASK_NAME = "APPLY daily run"`.
  - All `schtasks` calls go through `_run`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_schedule.py`. Reuse the file's existing spy helper for
`_run` if it fits; otherwise use the inline spy below.

```python
def test_windows_gets_task_scheduler(monkeypatch):
    from apply import schedule as s
    assert isinstance(s.backend("win32"), s.TaskSchedulerBackend)


def test_task_xml_runs_daily_catches_up_and_logs(tmp_path, monkeypatch):
    from apply import schedule as s
    monkeypatch.setattr(s.shutil, "which", lambda n: r"C:\Users\f\.local\bin\uv.exe" if n == "uv" else None)
    plan = s.Schedule(hour=6, minute=30, project=tmp_path, command="uv run apply run --notify --llm api")
    xml = s.TaskSchedulerBackend().render(plan)
    assert "<StartBoundary>2026-01-01T06:30:00</StartBoundary>" in xml
    assert "<DaysInterval>1</DaysInterval>" in xml
    assert "<StartWhenAvailable>true</StartWhenAvailable>" in xml
    assert "<RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>" in xml
    assert "<LogonType>InteractiveToken</LogonType>" in xml
    assert f"<WorkingDirectory>{tmp_path}</WorkingDirectory>" in xml
    assert r"C:\Users\f\.local\bin\uv.exe" in xml and "run apply run --notify --llm api" in xml
    assert "&gt;&gt;" in xml and r"out\run.log" in xml


def test_task_install_imports_utf16_xml_through_run(tmp_path, monkeypatch):
    import subprocess
    from apply import schedule as s
    calls = []
    monkeypatch.setattr(s.shutil, "which", lambda n: r"C:\uv.exe" if n == "uv" else None)
    monkeypatch.setattr(s, "_run", lambda argv, stdin=None: calls.append(argv) or subprocess.CompletedProcess(argv, 0, "", ""))
    name = s.TaskSchedulerBackend().install(s.Schedule(hour=7, minute=5, project=tmp_path))
    assert name == s.TASK_NAME
    create = calls[0]
    assert create[:2] == ["schtasks", "/Create"] and "/F" in create
    xml_path = create[create.index("/XML") + 1]
    assert open(xml_path, encoding="utf-16").read().startswith('<?xml version="1.0" encoding="UTF-16"?>')


def test_task_status_reads_back_the_time(monkeypatch):
    import subprocess
    from apply import schedule as s
    xml = "<Task><StartBoundary>2026-01-01T07:05:00</StartBoundary><Arguments>/c run</Arguments></Task>"
    monkeypatch.setattr(s, "_run", lambda argv, stdin=None: subprocess.CompletedProcess(argv, 0, xml, ""))
    state = s.TaskSchedulerBackend().status()
    assert state["installed"] and state["at"] == "07:05"


def test_task_remove(monkeypatch):
    import subprocess
    from apply import schedule as s
    monkeypatch.setattr(s, "_run", lambda argv, stdin=None: subprocess.CompletedProcess(argv, 0, "", ""))
    assert s.TaskSchedulerBackend().remove() is True
```

- [ ] **Step 2: Run them to see the failures**

```bash
uv run pytest tests/test_schedule.py -v -k "task or windows"
```

Expected: FAIL.

- [ ] **Step 3: Implement**

In `schedule.py`, add `from xml.sax.saxutils import escape`, then:

```python
TASK_NAME = "APPLY daily run"


class TaskSchedulerBackend:
    """Windows. A scheduled task with StartWhenAvailable (launchd's catch-up)
    and the user's interactive token, so Credential Manager is readable without
    storing a password."""

    def render(self, schedule: Schedule) -> str:
        uv = shutil.which("uv") or "uv"
        args = schedule.command.split(" ", 1)[1] if schedule.command.startswith("uv ") else schedule.command
        action = f'/c ""{uv}" {args} >> "out\\run.log" 2>> "out\\run.err""'
        return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>{escape(TASK_NAME)}: discover, ingest, write. Never submits.</Description></RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>2026-01-01T{schedule.hour:02d}:{schedule.minute:02d}:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>cmd.exe</Command>
      <Arguments>{escape(action)}</Arguments>
      <WorkingDirectory>{escape(str(schedule.project))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""

    def install(self, schedule: Schedule) -> str:
        if not shutil.which("uv"):
            raise RuntimeError("uv is not on PATH; the scheduled task would not find it.")
        schedule.log.parent.mkdir(parents=True, exist_ok=True)
        xml_path = schedule.log.parent / "apply-task.xml"
        xml_path.write_text(self.render(schedule), encoding="utf-16")
        result = _run(["schtasks", "/Create", "/TN", TASK_NAME, "/XML", str(xml_path), "/F"])
        if not _ok(result):
            raise RuntimeError((result.stderr or result.stdout or "schtasks /Create failed").strip())
        return TASK_NAME

    def remove(self) -> bool:
        return _ok(_run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]))

    def status(self) -> dict:
        result = _run(["schtasks", "/Query", "/TN", TASK_NAME, "/XML", "ONE"])
        if not _ok(result):
            return {"installed": False}
        xml = result.stdout or ""
        when = re.search(r"<StartBoundary>[^T<]*T(\d\d):(\d\d)", xml)
        args = re.search(r"<Arguments>(.*?)</Arguments>", xml, re.S)
        return {"installed": True, "path": f"Task Scheduler › {TASK_NAME}",
                "at": f"{when.group(1)}:{when.group(2)}" if when else "?",
                "loaded": True, "command": args.group(1) if args else "",
                "log": r"out\run.log"}
```

In `backend()`, before the `raise`, add:

```python
    if name.startswith("win"):
        return TaskSchedulerBackend()
```

Leave the raise message ("…your own cron") for other platforms, because
`test_fresh_clone` asserts on it.

Update the module docstring's first paragraph: "Four backends, one
interface… Windows gets Task Scheduler with StartWhenAvailable."

- [ ] **Step 4: Run the full suite on both Pythons**

```bash
uv run --python 3.11 pytest -q && uv run --python 3.13 pytest -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/apply/schedule.py src/apply/cli.py tests/test_schedule.py tests/test_fresh_clone.py
git commit -m "Windows gets the morning run: a Task Scheduler backend

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Tracks become configuration

**Files:**
- Modify:
  - `src/apply/search.defaults.yaml`: a new `tracks:` block, holding today's
    `classify.SIGNALS` verbatim
  - `src/apply/search.py`: `TrackSpec`; `SearchConfig.tracks` and
    `.default_track`; `build`
  - `src/apply/models.py:17-29`: `Track` becomes a validated `str`
  - `src/apply/classify.py`: signals come from config
  - `src/apply/score.py:274-281`: pass the config to classify
  - `src/apply/parse.py:403`
  - `src/apply/generate.py:651-690`: template fallback, `code_link`, resume
    layout
  - `src/apply/cli.py:382,510,881,891`: track lists from config
  - `src/apply/web/routes.py:24,54,140,151,166`: track lists from config
- Create: `templates/letters/generic.tex.j2`, `tests/test_tracks.py`
- Modify tests: `tests/test_classify.py` (`is` → `==` only)
- Read first: gap-analysis §2.2 and §R3 (every call site, file:line).

**Interfaces:**
- Produces:
  - `search.TrackSpec(name: str, keywords: tuple[tuple[str, int], ...], resume: str, code_link: bool)`.
    `resume` is either `"projects_first"` or `"experience_first"`.
  - `SearchConfig.tracks: tuple[TrackSpec, ...]`, `SearchConfig.default_track: str`,
    and `SearchConfig.track(name) -> TrackSpec`. The last falls back to the
    default track's spec for an unknown name.
  - `search.RESUME_TEMPLATES = {"projects_first": "resume_quant", "experience_first": "resume_traditional"}`
  - `models.Track(str)` with `.value`, `Track.parse(value) -> Track` (validated
    against `search.load().tracks`; error text keeps "unknown track …;
    expected one of: …"), and the constants `Track.QUANT`, `BANKING`,
    `ALLOCATOR` and `CORPORATE`.
  - `classify.classify(text: str, config: SearchConfig | None = None) -> Classification`.
    Keys are `Track`; a tie or zero resolves to `config.default_track`.
  - `generate.select_resume(track: str) -> str`

- [ ] **Step 1: Write the failing tests**

`tests/test_tracks.py`:

```python
from __future__ import annotations

import yaml

SWE = {"tracks": {"default": "swe", "kinds": {
    "swe": {"resume": "projects_first", "code_link": True,
            "keywords": [["software engineer", 5], ["backend", 3], ["python", 2]]},
    "data": {"resume": "experience_first", "code_link": False,
             "keywords": [["data analyst", 5], ["sql", 3], ["tableau", 3]]}}}}


def _use(isolated_data_dir, body):
    from apply import search
    (isolated_data_dir / "search.yaml").write_text(yaml.safe_dump(body), encoding="utf-8")
    search._load_cached.cache_clear()


def test_defaults_are_todays_four_tracks():
    from apply import search
    cfg = search.load()
    assert [t.name for t in cfg.tracks] == ["quant", "banking", "allocator", "corporate"]
    assert cfg.default_track == "corporate"
    assert cfg.track("quant").resume == "projects_first" and cfg.track("quant").code_link
    assert not cfg.track("banking").code_link


def test_defaults_carry_todays_keyword_weights():
    from apply import search
    quant = dict(search.load().track("quant").keywords)
    assert quant["market making"] == 5 and quant["python"] == 1 and quant["pricing model"] == 4


def test_configured_tracks_replace_the_defaults(isolated_data_dir):
    from apply.classify import classify
    _use(isolated_data_dir, SWE)
    assert classify("Backend software engineer, Python").track == "swe"
    assert classify("Data analyst: SQL and Tableau").track == "data"
    assert classify("nothing relevant").track == "swe"


def test_track_parse_follows_the_config(isolated_data_dir):
    import pytest
    from apply.models import Track
    with pytest.raises(ValueError, match="expected one of: quant, banking, allocator, corporate"):
        Track.parse("swe")
    _use(isolated_data_dir, SWE)
    assert Track.parse("SWE") == "swe"


def test_a_custom_track_renders_through_the_generic_letter(isolated_data_dir, workspace, profile, quillon_jd):
    from conftest import posting_from
    from apply import generate
    _use(isolated_data_dir, SWE)
    assert generate.select_resume("swe") == "resume_quant"
    assert generate.select_resume("data") == "resume_traditional"
    posting = posting_from(quillon_jd, track="swe")
    letter = generate.Letter(**_letter_kwargs())
    tex = generate.render_letter(profile, posting, letter)
    assert "One." in tex and "Four." in tex


def _letter_kwargs():
    """Build the smallest valid Letter. Read generate.Letter's fields and fill
    them: four paragraphs 'One.'..'Four.', a closing, a salutation, a signoff."""
    raise NotImplementedError   # implementer: replace with the real constructor kwargs
```

`_letter_kwargs` is the one place the implementer must read
`generate.Letter`'s dataclass and write real kwargs. That is a deliberate
instruction, not a placeholder in the shipped test: the finished test must
not raise `NotImplementedError`.

Also check the fixture names (`isolated_data_dir`, `workspace`,
`quillon_jd`) against `tests/conftest.py`. The gap analysis lists them; if
`isolated_data_dir` is autouse and yields a path, use it as written.

- [ ] **Step 2: Run them to see the failures**

```bash
uv run pytest tests/test_tracks.py -v
```

Expected: FAIL.

- [ ] **Step 3: Move the signals into YAML**

Append to `src/apply/search.defaults.yaml`:

```yaml


# ------------------------------------------------------------------ tracks
#
# The kinds of role this search is for. Each decides three things: which
# keywords pull a posting toward it (classify.py), which resume layout goes out
# with it (projects_first or experience_first), and whether its letter may
# offer a link to the proof project's code. A posting matching none of them,
# or tied between several, becomes `default`. Phrases are literal text matched
# on word boundaries, not regexes. Weight 5 is decisive, 1 is weak; repetition
# counts up to three times.

tracks:
  default: corporate
  kinds:
    quant:
      resume: projects_first
      code_link: true
      keywords:
        - ["market making", 5]
        # ... every (phrase, weight) pair from classify.SIGNALS[Track.QUANT], in order
    banking:
      resume: experience_first
      code_link: false
      keywords: []      # ... from SIGNALS[Track.BANKING]
    allocator:
      resume: experience_first
      code_link: false
      keywords: []      # ... from SIGNALS[Track.ALLOCATOR]
    corporate:
      resume: experience_first
      code_link: false
      keywords: []      # ... from SIGNALS[Track.CORPORATE]
```

Generate the four lists mechanically rather than retyping them. Keep the
order and any duplicates exactly; duplicates like `"investment office"` in
allocator count twice today.

```bash
uv run python -c "
from apply.classify import SIGNALS
for t, sig in SIGNALS.items():
    print(t.value)
    for p, w in sig: print(f'        - [{p!r}, {w}]'.replace(\"'\", '\"'))
"
```

Then delete `SIGNALS` from `classify.py`.

- [ ] **Step 4: `search.py`**

```python
RESUME_TEMPLATES = {"projects_first": "resume_quant", "experience_first": "resume_traditional"}


@dataclass(frozen=True, slots=True)
class TrackSpec:
    name: str
    keywords: tuple[tuple[str, int], ...]
    resume: str = "experience_first"
    code_link: bool = False


def _tracks(block: dict | None, where: str) -> tuple[tuple[TrackSpec, ...], str]:
    block = block or {}
    kinds = block.get("kinds") or {}
    if not kinds:
        raise KeyError(f"search config: tracks.kinds is empty ({where})")
    specs = []
    for name, body in kinds.items():
        body = body or {}
        resume = body.get("resume", "experience_first")
        if resume not in RESUME_TEMPLATES:
            raise ValueError(f"search config: tracks.kinds.{name}.resume must be one of "
                             f"{sorted(RESUME_TEMPLATES)} ({where})")
        specs.append(TrackSpec(
            name=str(name).strip().lower(),
            keywords=tuple((str(p).lower(), int(w)) for p, w in (body.get("keywords") or [])),
            resume=resume, code_link=bool(body.get("code_link", False))))
    default = str(block.get("default") or specs[0].name).lower()
    if default not in {s.name for s in specs}:
        raise ValueError(f"search config: tracks.default {default!r} is not a track ({where})")
    return tuple(specs), default
```

Add the fields `tracks: tuple[TrackSpec, ...]` and `default_track: str` to
`SearchConfig`. They come after the existing required fields. If
`SearchConfig` is constructed anywhere other than `build`
(`grep -rn "SearchConfig(" src tests tools`), give both fields defaults of
`()` and `"corporate"`. Add the method:

```python
    def track(self, name: str) -> TrackSpec:
        by_name = {t.name: t for t in self.tracks}
        return by_name.get(str(name), by_name[self.default_track])
```

In `build`, compute
`tracks, default_track = _tracks(raw.get("tracks"), sources.get("tracks", "defaults"))`
and pass both. Make sure `_size` handles the `tracks` block, and later the
`limits` block: for a dict, return the number of `kinds`, or `len(block)`.
Read `_size` and keep `apply search` output sensible.

- [ ] **Step 5: `Track` and `classify`**

`models.py`:

```python
class Track(str):
    """A track name, validated against the search configuration's `tracks`
    (search.defaults.yaml, or data/search.yaml) — a user in another field
    defines their own."""

    __slots__ = ()

    @property
    def value(self) -> str:
        return str(self)

    @classmethod
    def parse(cls, value: str) -> "Track":
        from .search import load

        names = [t.name for t in load().tracks]
        key = str(value).strip().lower()
        if key not in names:
            raise ValueError(f"unknown track {value!r}; expected one of: {', '.join(names)}")
        return cls(key)


Track.QUANT, Track.BANKING, Track.ALLOCATOR, Track.CORPORATE = (
    Track("quant"), Track("banking"), Track("allocator"), Track("corporate"))
```

`classify.py`: keep `_pattern` and the docstring, and replace the rest:

```python
@dataclass(slots=True)
class Classification:
    track: Track
    scores: dict
    matched: dict = field(default_factory=dict)
    tied: bool = False
    default: str = "corporate"

    @property
    def why(self) -> str:
        hits = self.matched.get(self.track, [])
        if not hits:
            return f"{self.track} (no keywords matched; defaulted)"
        if self.tied:
            return f"{self.track} (tie broken toward {self.default}) — {', '.join(hits)}"
        return f"{self.track} ({self.scores[self.track]}) — {', '.join(hits)}"

    def table(self) -> list[tuple[str, int, str]]:
        return [(t, self.scores[t], ", ".join(self.matched.get(t, [])) or "—")
                for t in sorted(self.scores, key=lambda t: -self.scores[t])]


@lru_cache(maxsize=8)
def _compiled(tracks: tuple) -> dict:
    return {Track(spec.name): [(p, w, _pattern(p)) for p, w in spec.keywords] for spec in tracks}


def classify(text: str, config=None) -> Classification:
    from .search import load

    config = config or load()
    scores, matched = {}, {}
    for track, signals in _compiled(config.tracks).items():
        total, hits = 0, []
        for phrase, weight, pattern in signals:
            n = len(pattern.findall(text))
            if n:
                # Repetition is evidence, with sharply diminishing returns.
                total += weight * min(n, 3)
                hits.append(phrase)
        scores[track], matched[track] = total, hits
    best = max(scores.values())
    leaders = [t for t, s in scores.items() if s == best]
    tied = len(leaders) > 1 or best == 0
    # Ties resolve to the default track: the least over-claiming thing to be wrong about.
    track = Track(config.default_track) if tied else leaders[0]
    return Classification(track=track, scores=scores, matched=matched, tied=tied,
                          default=config.default_track)
```

`TrackSpec` is frozen, so `config.tracks` is hashable and the `lru_cache`
works. Import `lru_cache` from `functools`.

Make sure `.why`'s text for the tie case is unchanged under the defaults: it
used to say "tie broken toward corporate". Grep tests for that string.

`score.py`: `classification = classify(haystack, config)`, and
`track = classification.track.value`. That is unchanged otherwise.

`parse.py:403`: `classify(text)` stays as it is (it uses `load()`).

`tests/test_classify.py`: `is Track.X` → `== Track.X`. That is the only
permitted change.

- [ ] **Step 6: `generate.py`, the CLI and the web**

Replace `RESUME_VARIANT` and `select_resume`:

```python
def select_resume(track: str) -> str:
    from .search import RESUME_TEMPLATES, load

    return RESUME_TEMPLATES[load().track(str(track)).resume]
```

In `render_letter` (generate.py:651-660):

```python
    from .search import load

    track = str(posting.track)
    name = f"letters/{track}.tex.j2"
    if not (templates_dir() / name).exists():
        name = "letters/generic.tex.j2"
    template = env.get_template(name)
    spec = load().track(track)
    proof_url = None
    body = letter.full_text.lower()
    for project in profile.projects.values():
        if spec.code_link and project.url and project.name.lower() in body and track in project.tracks:
            proof_url = project.url
            break
```

**Equivalence:** today, only the quant template renders `proof_url`, and the
rule is `"quant" in project.tracks`. Quant is the only default track with
`code_link: true`, so the output is identical for the owner. Keep the
existing comment's intent.

`templates/letters/generic.tex.j2`: copy `quant.tex.j2`, changing the first
comment to
`<# Any track without a template of its own. Offers the code only when the track sets code_link. #>`
and "The code is public:" to "The work is public:".

`cli.py`:
- `status --track` help: "one of the tracks in your search configuration
  (`apply search`)".
- `Track.parse` calls stay; they validate against config now.

`web/routes.py`:
- `for t in Track` → `for t in (s.name for s in search_mod.load().tracks)`.
- `tracks=[t.value for t in Track]` → that list.
- `Form("corporate")` → `Form(None)`, defaulting to `load().default_track`.

- [ ] **Step 7: Run everything, the frozen corpora included**

```bash
uv run --python 3.11 pytest -q && uv run --python 3.13 pytest -q
```

Expected: all pass. That includes `tests/test_score.py` (unmodified),
`tests/test_search_config.py` (the gate corpus) and the owner's local corpus
test.

- [ ] **Step 8: Commit**

```bash
git add src/apply/search.defaults.yaml src/apply/search.py src/apply/models.py src/apply/classify.py src/apply/score.py src/apply/parse.py src/apply/generate.py src/apply/cli.py src/apply/web/routes.py templates/letters/generic.tex.j2 tests/test_tracks.py tests/test_classify.py
git commit -m "Tracks are configuration: their keywords, resume layout and code link move to the YAML

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: The gate's last hardcoded limits move to the YAML

**Files:**
- Modify: `src/apply/search.defaults.yaml` (a `limits:` block),
  `src/apply/search.py` (`SearchConfig.limits`), `src/apply/score.py`
  (the `YEARS` cutoff, `ADVANCED_DEGREE`, `GRADUATE_PROGRAM` gates)
- Test: `tests/test_search_config.py` (append)

**Interfaces:**
- Produces: `SearchConfig.limits: dict` with three keys:
  - `max_years_experience: int | None`
  - `advanced_degree_required: bool`
  - `graduate_programs: bool`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_search_config.py`. Use the file's existing helper for
writing `data/search.yaml` (gap-analysis cites lines 316-340). The tests
below assume a local helper `_override(isolated_data_dir, body)` that writes
the YAML and clears `search._load_cached`; use whatever that file already
calls it.

```python
SWE_SEATTLE = {
    "rejects": {"seniority": ["senior", "staff", "principal", "manager"],
                "off_function": ["sales", "recruiter"], "too_technical": []},
    "geography": {"primary": {"label": "Seattle", "weight": 25, "patterns": ["seattle", "bellevue"]},
                  "remote": {"label": "remote", "weight": 10, "patterns": ["remote"], "match_title": True}},
    "role_fit": [[r"software\s+engineer", 25], [r"backend", 20]],
    "timing": [[r"new\s+grad", 18]],
    "title_timing": [[r"\b2027\b", 14]],
    "tracks": {"default": "swe", "kinds": {"swe": {"resume": "projects_first", "code_link": True,
                                                    "keywords": [["software engineer", 5], ["backend", 3]]}}},
    "limits": {"max_years_experience": 2, "advanced_degree_required": True, "graduate_programs": True},
}


def _p(title, location="Seattle, WA", body=""):
    from apply.sources.base import RawPosting
    return RawPosting(employer="Co", title=title, url="https://x", source="t",
                      location=location, description=body, employer_priority=1)


def test_a_software_engineering_search_pursues_swe_roles(isolated_data_dir):
    from apply.score import Verdict, score
    _override(isolated_data_dir, SWE_SEATTLE)
    r = score(_p("Software Engineer, New Grad 2027"))
    assert r.verdict is Verdict.PURSUE, r.reasons
    assert "Seattle +25" in r.reasons
    assert score(_p("Backend Engineer")).rejected_by != "technical"
    assert score(_p("Summer Analyst, Investment Banking")).verdict is not Verdict.PURSUE


def test_the_years_bar_is_configurable(isolated_data_dir):
    from apply.score import score
    _override(isolated_data_dir, SWE_SEATTLE)
    assert score(_p("Software Engineer", body="2+ years of experience")).rejected_by == "experience"
    _override(isolated_data_dir, {**SWE_SEATTLE, "limits": {"max_years_experience": None}})
    assert score(_p("Software Engineer", body="5+ years of experience")).rejected_by != "experience"


def test_degree_gates_can_be_turned_off(isolated_data_dir):
    from apply.score import score
    _override(isolated_data_dir, {**SWE_SEATTLE, "limits": {"advanced_degree_required": False,
                                                              "graduate_programs": False}})
    assert score(_p("PhD Software Engineer Intern")).rejected_by != "degree"
    assert score(_p("Software Engineer", body="A PhD is required.")).rejected_by != "degree"


def test_default_limits_are_todays():
    from apply import search
    assert search.load().limits == {"max_years_experience": 3, "advanced_degree_required": True,
                                    "graduate_programs": True}
```

- [ ] **Step 2: Run them to see the failures**

```bash
uv run pytest tests/test_search_config.py -v -k "software or years or degree_gates or default_limits"
```

Expected: FAIL.

- [ ] **Step 3: Implement**

Add to `search.defaults.yaml`:

```yaml


# ------------------------------------------------------------------ limits
#
# Career-stage bars the gate applies to every posting. These defaults are for
# an undergraduate: a posting asking for three or more years is refused, and so
# is one whose body requires an advanced degree or whose title names a PhD,
# MBA or master's programme. An experienced hire raises or nulls the first;
# a graduate student turns the other two off.

limits:
  max_years_experience: 3        # null turns the experience bar off
  advanced_degree_required: true
  graduate_programs: true
```

In `search.py`:
- Add `limits: dict` to `SearchConfig` (with a default, if constructed
  elsewhere).
- In `build`, add:

```python
        limits={"max_years_experience": 3, "advanced_degree_required": True,
                "graduate_programs": True, **(raw.get("limits") or {})},
```

In `score.py`:
- Guard `GRADUATE_PROGRAM` with `config.limits["graduate_programs"]`.
- Change the years check to

  ```python
  cap = config.limits["max_years_experience"]
  if years and cap is not None and int(years.group(1)) >= cap:
  ```

- Guard `ADVANCED_DEGREE` with `config.limits["advanced_degree_required"]`.

A data/search.yaml `limits:` block replaces the whole block (`_merge`), so
keys it leaves out fall back to the defaults above through the `**` merge in
`build`. Intended.

- [ ] **Step 4: Run the full suite on both Pythons**

```bash
uv run --python 3.11 pytest -q && uv run --python 3.13 pytest -q
```

Expected: all pass, with both corpora unchanged.

- [ ] **Step 5: Commit**

```bash
git add src/apply/search.defaults.yaml src/apply/search.py src/apply/score.py tests/test_search_config.py
git commit -m "The experience and degree bars become configuration, for searches that are not an undergraduate's

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Find a firm's board from its name

**Files:**
- Modify: `src/apply/resolve.py` (gap-analysis §2.4 and Part 3 step 8 list
  its API)
- Test: `tests/test_resolve_probe.py` (new)

**Interfaces:**
- Produces:
  - `resolve.slug_candidates(name: str) -> list[str]`
  - `resolve.probe_slugs(name: str, verify_fn=None) -> tuple[Candidate, int] | None`.
    It tries Greenhouse, then Lever, then Ashby for each slug, and returns the
    first with a positive count.
  - `Candidate.as_yaml(name, priority=3, search: list[str] | None = None)`.
    Workday and Eightfold `search:` use `search` when it is given.
  - `Candidate.as_entry(name: str, priority: int, search: list[str], tracks: list[str]) -> dict`
  - `verify(candidate, name="probe", search=None)` uses `search or ["analyst"]`.

- [ ] **Step 1: Write the failing tests**

```python
from __future__ import annotations

from apply import resolve


def test_slug_candidates():
    assert resolve.slug_candidates("Jane Street Capital, LLC")[:3] == [
        "janestreetcapital", "jane-street-capital", "janestreet"]


def test_probe_returns_first_verified_board():
    seen = []

    def fake_verify(candidate, name="probe", search=None):
        seen.append((candidate.ats, candidate.config["board"]))
        return 12 if (candidate.ats, candidate.config["board"]) == ("lever", "acme") else None

    found = resolve.probe_slugs("Acme", verify_fn=fake_verify)
    assert found[0].ats == "lever" and found[1] == 12
    assert seen[0] == ("greenhouse", "acme")


def test_probe_gives_up_honestly():
    assert resolve.probe_slugs("Nobody", verify_fn=lambda c, name="p", search=None: None) is None


def test_entry_carries_the_users_search_terms():
    c = resolve.Candidate(ats="workday", evidence="", supported=True,
                          config={"host": "x.wd1.myworkdayjobs.com", "tenant": "x", "site": "X"})
    entry = c.as_entry("X Corp", 2, ["software engineer", "new grad"], ["swe"])
    assert entry["search"] == ["software engineer", "new grad"] and entry["tracks"] == ["swe"]
    assert 'search: ["software engineer", "new grad"]' in c.as_yaml("X Corp", search=["software engineer", "new grad"])
```

Check `Candidate`'s real field order in `resolve.py` and adjust the
constructor call to match.

- [ ] **Step 2: Run them to see the failures**

```bash
uv run pytest tests/test_resolve_probe.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement**

```python
_NAME_SUFFIX = re.compile(r"\b(inc|llc|lp|llp|ltd|plc|corp|corporation|co|company|group|holdings)\b\.?", re.I)


def slug_candidates(name: str) -> list[str]:
    """The slugs a firm's board most often lives under, most likely first."""
    words = re.findall(r"[a-z0-9]+", _NAME_SUFFIX.sub(" ", name.lower()))
    out = ["".join(words), "-".join(words)]
    if len(words) > 1:
        out += ["".join(words[:-1]), words[0]]
    return list(dict.fromkeys(s for s in out if s))


def probe_slugs(name: str, verify_fn=None) -> tuple["Candidate", int] | None:
    """Try the public board APIs under the likely slugs. Only an answer with
    postings counts — a guess is never written to the registry."""
    verify_fn = verify_fn or verify
    for slug in slug_candidates(name):
        for ats in ("greenhouse", "lever", "ashby"):
            candidate = Candidate(ats=ats, evidence=f"probed {ats}:{slug}",
                                  config={"board": slug}, supported=True)
            count = verify_fn(candidate, name)
            if count:
                return candidate, count
    return None
```

Rework `as_yaml` so the `search:` line is
`"    search: [" + ", ".join(json.dumps(t) for t in (search or ["analyst", "intern", "2027"])) + "]"`.
Default to today's terms, so the existing tests keep passing.

Add:

```python
    def as_entry(self, name: str, priority: int, search: list[str], tracks: list[str]) -> dict:
        entry = {"name": name, "ats": self.ats, **self.config, "tracks": tracks, "priority": priority}
        if self.ats in ("workday", "eightfold"):
            entry["search"] = search
            entry["max_results"] = 120
        return entry
```

`probe_slugs` sends requests through `verify` (adapter fetches), from
`apply.resolve`. That module is already declared in `outbound.py`, so nothing
needs declaring.

- [ ] **Step 4: Run the full suite**

```bash
uv run pytest -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/apply/resolve.py tests/test_resolve_probe.py
git commit -m "Find a firm's board from its name, verified against the public API before it is written

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: `setup` becomes a package; document extraction and redaction

**Files:**
- Move: `src/apply/setup.py` → `src/apply/setup/__init__.py`, unchanged
  except for relative imports (`.generate` → `..generate`, `.profile` →
  `..profile`, and so on)
- Create: `src/apply/setup/extract.py`, `tests/test_setup_extract.py`
- Check: `pyproject.toml` hatch config (the package is under
  `packages = ["src/apply"]`, so subpackages are included)

**Interfaces:**
- Produces:
  - `extract.Unreadable(ValueError)`
  - `extract.read_document(path: Path) -> str`, for `.pdf`, `.docx`, `.txt`
    and `.md`
  - `extract.redact(text, *, phone=None, address=None) -> str`
  - `extract.contains_forbidden(text) -> bool`
  - `MAX_DOCX_XML = 20_000_000`

- [ ] **Step 1: Move the module and check nothing broke**

```bash
mkdir -p src/apply/setup && git mv src/apply/setup.py src/apply/setup/__init__.py
```

In `src/apply/setup/__init__.py`, change every `from .x import` to
`from ..x import`, and every `from . import x` to `from .. import x`.

```bash
uv run pytest -q
```

Expected: all pass. `EXAMPLE_PROFILE = repo_root() / ...` is unaffected.

- [ ] **Step 2: Write the failing tests**

`tests/test_setup_extract.py`:

```python
from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from apply.setup import extract

DOCX_XML = ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Jordan Reyes</w:t></w:r></w:p>'
            '<w:p><w:r><w:t xml:space="preserve">Analyst — </w:t></w:r><w:r><w:t>Acme Capital</w:t></w:r></w:p>'
            '<w:p><w:r><w:t>Tab</w:t></w:r><w:r><w:tab/></w:r><w:r><w:t>bed</w:t></w:r></w:p></w:body></w:document>')


def make_docx(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("word/document.xml", DOCX_XML)
    return path


def test_docx_paragraphs_become_lines(tmp_path):
    assert extract.read_document(make_docx(tmp_path / "r.docx")).splitlines() == [
        "Jordan Reyes", "Analyst — Acme Capital", "Tab\tbed"]


def test_txt_and_md(tmp_path):
    p = tmp_path / "r.md"
    p.write_text("# Me\nThings — done.", encoding="utf-8")
    assert extract.read_document(p) == "# Me\nThings — done."


def test_pdf_goes_through_pypdf(tmp_path, monkeypatch):
    class Page:
        def extract_text(self):
            return "Page one"

    class Reader:
        def __init__(self, path):
            self.pages = [Page(), Page()]

    monkeypatch.setattr("pypdf.PdfReader", Reader)
    p = tmp_path / "r.pdf"
    p.write_bytes(b"%PDF-1.4")
    assert extract.read_document(p) == "Page one\n\nPage one"


def test_unknown_type_says_what_to_do(tmp_path):
    p = tmp_path / "r.pages"
    p.write_bytes(b"x")
    with pytest.raises(extract.Unreadable, match="PDF, DOCX"):
        extract.read_document(p)


def test_oversized_docx_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(extract, "MAX_DOCX_XML", 10)
    with pytest.raises(extract.Unreadable, match="too large"):
        extract.read_document(make_docx(tmp_path / "r.docx"))


def test_redact_phone_address_and_ssn():
    text = ("Jordan Reyes · (804) 555-0123 · +1 804.555.0199\n"
            "123 Main Street, Richmond, VA 23220\nSSN 123-45-6789\nGPA 3.9, 2025-08, 40% faster")
    out = extract.redact(text, phone="(804) 555-0123", address="123 Main Street, Richmond, VA 23220")
    assert "555" not in out and "Main Street" not in out and "6789" not in out
    assert "GPA 3.9, 2025-08, 40% faster" in out


def test_forbidden_answers():
    assert extract.contains_forbidden("my ssn is 123-45-6789")
    assert extract.contains_forbidden("DOB: 01/02/2003")
    assert extract.contains_forbidden("date of birth 2003-01-02")
    assert not extract.contains_forbidden("graduating 2027-05; 3 years of Python")
```

The word "Richmond" appears in this fixture text. If `AUTHORS_BIOGRAPHY`'s
check ever widens to all tests, replace it with "Springfield". Use
"Springfield" now to be safe.

- [ ] **Step 3: Run them to see the failures**

```bash
uv run pytest tests/test_setup_extract.py -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 4: Implement `src/apply/setup/extract.py`**

```python
"""A resume or a letter, as plain text — with what must never leave the machine taken out.

The text goes two places: data/context/ (which every letter request sends to
the API) and the one drafting request. Phone and street address are withheld
from the API by design, so they are removed here, before either.

The .docx parser is the standard library's. ElementTree on Python 3.11+ does
not resolve external entities, and the bundled expat caps entity expansion;
the input is the user's own resume on their own machine, and a size cap
refuses anything that is plainly not one.
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree

MAX_DOCX_XML = 20_000_000


class Unreadable(ValueError):
    """Not a document we can read; the message says which kinds are."""


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def _docx(path: Path) -> str:
    with zipfile.ZipFile(path) as z:
        if z.getinfo("word/document.xml").file_size > MAX_DOCX_XML:
            raise Unreadable(f"{path.name}: that .docx is too large to be a resume")
        root = ElementTree.fromstring(z.read("word/document.xml"))
    lines = []
    for para in root.iter(f"{_W}p"):
        bits = []
        for node in para.iter():
            if node.tag == f"{_W}t" and node.text:
                bits.append(node.text)
            elif node.tag == f"{_W}tab":
                bits.append("\t")
            elif node.tag in (f"{_W}br", f"{_W}cr"):
                bits.append("\n")
        line = "".join(bits).rstrip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def _pdf(path: Path) -> str:
    from pypdf import PdfReader

    pages = [(page.extract_text() or "").strip() for page in PdfReader(str(path)).pages]
    return "\n\n".join(p for p in pages if p)


def read_document(path: Path) -> str:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".docx":
        return _docx(path)
    if suffix == ".pdf":
        return _pdf(path)
    if suffix in (".txt", ".md"):
        return path.read_text(encoding="utf-8", errors="replace").strip()
    raise Unreadable(f"{path.name}: save it as PDF, DOCX, TXT or MD and try again.")


_PHONE = re.compile(r"(?<![\d-])(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?![\d-])")
_SSN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")
_STREET = re.compile(
    r"\b\d{1,6}\s+(?:[A-Z][a-z]+\.?\s+){1,4}(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Boulevard|Ln|Lane|"
    r"Dr|Drive|Ct|Court|Way|Pl|Place|Ter|Terrace|Pkwy|Parkway|Cir|Circle)\b\.?[^\n]*")
FORBIDDEN = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)|\bssn\b|social\s+security|\bdob\b|date\s+of\s+birth",
                       re.I)


def contains_forbidden(text: str) -> bool:
    return bool(FORBIDDEN.search(text or ""))


def redact(text: str, *, phone: str | None = None, address: str | None = None) -> str:
    out = text
    if address:
        out = out.replace(address, "[address]")
    out = _STREET.sub("[address]", out)
    out = _SSN.sub("[removed]", out)
    if phone:
        out = out.replace(phone, "[phone]")
    return _PHONE.sub("[phone]", out)
```

- [ ] **Step 5: Run the full suite on both Pythons**

```bash
uv run --python 3.11 pytest -q && uv run --python 3.13 pytest -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/apply/setup tests/test_setup_extract.py
git commit -m "setup becomes a package; read PDF/DOCX/TXT resumes and redact phone, address and SSN

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: The draft — schema, request, grounding, files

**Files:**
- Create: `src/apply/setup/draft.py`, `tests/test_setup_draft.py`,
  `tests/fixtures/setup/draft.json`, `tests/fixtures/setup/resume.txt`
- Modify: `tests/conftest.py` (`FakeClaude` routes by schema and accepts
  `**kwargs`)

**Interfaces:**
- Consumes:
  - `llm.call(*, system, user, schema, model, effort, max_tokens=...)`
  - `llm.estimate`, `llm.DEFAULT_MODEL`
  - `budget.Budget.check(usd, purpose)` and `.record(usage, purpose, slug=None)`
  - `profile._digit_tokens`, `profile.ASK`
  - `setup.persona()`
  - `search.country_of`, `search._pattern_for`
- Produces:
  - `draft.Answers`, a dataclass with these fields:
    - `roles: str`, `job_types: list[str]`, `locations: list[str]`,
      `remote_ok: bool`, `firms: list[str]`, `avoid: str`, `links: dict`,
      `extra: str`
    - `work_authorized: bool`, `sponsorship_now: bool`,
      `sponsorship_future: bool`
    - `grad_expected: str` (YYYY-MM), `student: bool`,
      `availability_full_time: str | None`, `availability_internship: str | None`
    - `phone: str | None = None`, `street_address: str | None = None`,
      `gpa: str | None = None`
  - `draft.Draft`, the pydantic model below.
  - `draft.SECTIONS = ("identity", "experience", "projects", "skills", "writing", "search")`
  - `draft.request(sources: str, answers: Answers, note: str = "", *, budget=None) -> Draft`
  - `draft.ground(d: Draft, sources: str, answers: Answers) -> tuple[Draft, list[str]]`
  - `draft.to_files(d: Draft, answers: Answers) -> dict[str, dict]`, keyed
    `"profile.yaml"`, `"profile.private.yaml"` (only the keys the wizard owns)
    and `"search.yaml"`.

- [ ] **Step 1: Extend `FakeClaude`**

Make `__call__` accept `**kwargs`. Route by schema name:
- `Package` goes to the `packages` queue.
- `Review` goes to the `reviews` queue.
- Anything else goes to `self.others[schema.__name__]`, a dict of lists set
  through a new constructor argument, `others=None`.
- An unscripted schema raises
  `AssertionError(f"FakeClaude has nothing scripted for {schema.__name__}")`.

Existing tests are unaffected.

- [ ] **Step 2: Write the fixtures and the failing tests**

`tests/fixtures/setup/resume.txt`:

```
Jordan Reyes
jreyes@example.edu · (555) 201-4477
Blue Ridge University — B.S. Computer Science, expected May 2027
Acme Robotics — Software Intern, Jun 2025 – Aug 2025
- Cut test time 40% by parallelising the CI suite
- Wrote the fleet telemetry ingest service in Python
Projects
Kestrel — an order-book simulator in OCaml (github.com/jreyes-example/kestrel)
Skills: Python, OCaml, SQL, Git
```

Generate `tests/fixtures/setup/draft.json` with a short script. It builds a
valid `D.Draft(...)` for that person and dumps `model_dump_json(indent=1)`:
- identity: Jordan Reyes, jreyes@example.edu, Seattle WA
- education: Blue Ridge University, B.S., Computer Science, `start: "ASK"`,
  `current: true`
- experience: Acme Robotics, Software Intern, 2025-06 to 2025-08, the two
  bullets verbatim, `detail: []`, `tags: ["software"]`
- projects: `kestrel`, name Kestrel, url
  `https://github.com/jreyes-example/kestrel`, `tracks: ["swe"]`, short
  one_line / three_line / resume_line drawn from the resume, stack
  `[OCaml]`
- skills: `Languages: [Python, OCaml, SQL]`, `Tools: [Git]`
- voice etc.: short instruction strings
- one track `swe`: keywords software engineer 5, backend 3, python 2;
  `projects_first`; `code_link: true`; a proof_asset
- `default_track: "swe"`
- roles: `[{match: "software engineer", weight: 25}, {match: "backend engineer", weight: 22}]`
- timing: `[{match: "new grad", weight: 16}]`
- `title_timing: [{match: "2027", weight: 14}]`
- locations: Seattle 25 `["seattle", "bellevue"]`; remote 10 `["remote"]`
  with `title: true`
- reject: seniority `["senior", "staff", "principal", "manager"]`, functions
  `["sales", "recruiter"]`, technical `[]`
- `max_years_experience: 2`, `reject_advanced_degree: true`,
  `reject_graduate_programs: true`
- employers: Acme Robotics, `aliases: []`, `tracks: ["swe"]`, priority 1

`tests/test_setup_draft.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

from apply.setup import draft as D

FIX = Path(__file__).parent / "fixtures" / "setup"
SOURCES = (FIX / "resume.txt").read_text(encoding="utf-8")


def answers(**kw):
    base = dict(roles="backend software engineering", job_types=["internship", "full-time"],
                locations=["Seattle, WA"], remote_ok=True, firms=["Acme Robotics"], avoid="sales",
                links={"github": "https://github.com/jreyes-example"}, extra="",
                work_authorized=True, sponsorship_now=False, sponsorship_future=False,
                grad_expected="2027-05", student=True, availability_full_time=None,
                availability_internship="summer 2026")
    base.update(kw)
    return D.Answers(**base)


def canned() -> D.Draft:
    return D.Draft.model_validate(json.loads((FIX / "draft.json").read_text(encoding="utf-8")))


def test_grounding_drops_an_invented_figure_and_an_invented_employer():
    d = canned()
    d.experience[0].bullets.append("Grew revenue 300% in a quarter")
    d.experience.append(D.Experience(org="Globex", title="Intern", start="2024-06", end="2024-08",
                                     location="", bullets=["x"], detail=[], tags=[]))
    cleaned, notes = D.ground(d, SOURCES, answers())
    assert all("300%" not in b for b in cleaned.experience[0].bullets)
    assert [e.org for e in cleaned.experience] == ["Acme Robotics"]
    assert any("Globex" in n for n in notes) and any("300%" in n for n in notes)


def test_grounding_keeps_a_date_whose_year_is_sourced_and_asks_for_one_that_is_not():
    d = canned()
    cleaned, _ = D.ground(d, SOURCES, answers())
    assert cleaned.experience[0].start == "2025-06"
    d.experience[0].start = "2019-01"
    cleaned, _ = D.ground(d, SOURCES, answers())
    assert cleaned.experience[0].start == "ASK"


def test_grounding_removes_an_unsourced_link():
    d = canned()
    d.projects[0].url = "https://kestrel.example.com"
    cleaned, notes = D.ground(d, SOURCES, answers())
    assert cleaned.projects[0].url is None and any("link" in n for n in notes)


def test_authorization_and_graduation_come_from_answers_not_the_model():
    files = D.to_files(canned(), answers(work_authorized=False, sponsorship_future=True))
    auth = files["profile.yaml"]["authorization"]
    assert auth["us_work_authorized"] is False and auth["requires_sponsorship_future"] is True
    assert auth["requires_sponsorship_now"] is False
    current = [e for e in files["profile.yaml"]["education"] if e.get("current")][0]
    assert current["grad_expected"] == "2027-05"


def test_search_yaml_is_valid_and_complete():
    from apply import search
    files = D.to_files(canned(), answers())
    s = files["search.yaml"]
    for key in ("rejects", "geography", "role_fit", "timing", "title_timing", "tracks", "limits", "country"):
        assert key in s, key
    merged, sources = search._merge(search.yaml.safe_load(search.DEFAULTS.read_text(encoding="utf-8")), s)
    cfg = search.build(merged, sources)
    assert [t.name for t in cfg.tracks] == ["swe"] and cfg.limits["max_years_experience"] == 2
    assert cfg.geography[0][1] == "Seattle"


def test_private_keys_are_only_the_wizards_own():
    files = D.to_files(canned(), answers(phone="(555) 201-4477", gpa="3.8"))
    private = files["profile.private.yaml"]
    assert private["identity"]["phone"] == "(555) 201-4477"
    assert private["education_private"]["gpa"] == "3.8"
    assert private["identity"]["street_address"] == "ASK"


def test_files_load_as_a_profile(workspace):
    import yaml
    from apply.profile import Profile
    files = D.to_files(canned(), answers())
    data = workspace / "data"
    (data / "profile.yaml").write_text(yaml.safe_dump(files["profile.yaml"], sort_keys=False), encoding="utf-8")
    p = Profile.load()
    assert p.display_name.endswith("Reyes") and "swe" in p.projects["kestrel"].tracks


def test_request_goes_through_llm_call_and_the_ledger(monkeypatch, conn):
    from apply import llm
    from apply.budget import Budget
    seen = {}

    def fake_call(*, system, user, schema, model, effort, **kw):
        seen.update(schema=schema, user=user)
        return canned(), llm.Usage(model, input_tokens=40000, output_tokens=9000)

    monkeypatch.setattr(llm, "call", fake_call)
    budget = Budget(conn)                              # default $0.50 per call
    result = D.request(SOURCES, answers(phone="(555) 201-4477"), note="more weight on Seattle", budget=budget)
    assert seen["schema"] is D.Draft and "more weight on Seattle" in seen["user"]
    assert "201-4477" not in seen["user"]               # private answers never sent
    assert result.identity.legal_last == "Reyes"
    assert [row[0] for row in budget.by_purpose()] == ["setup"]
```

Check `Budget.by_purpose()`'s row shape and `search._merge`/`build`'s exact
signatures (gap analysis §2.3/R6), and adjust these assertions to them.

- [ ] **Step 3: Run them to see the failures**

```bash
uv run pytest tests/test_setup_draft.py -v
```

Expected: FAIL.

- [ ] **Step 4: Implement `src/apply/setup/draft.py`**

```python
"""From a resume and a few answers to a working configuration.

One request drafts everything; a deterministic pass then removes whatever the
user's own documents do not support, and the user approves each section before
a file is written. The model proposes; the documents and the user decide.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

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
    name: str = Field(description="lowercase, one word: 'swe', 'consulting', 'quant'")
    keywords: list[Keyword]
    resume: str = Field(description="'projects_first' or 'experience_first'")
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
    tracks: list[TrackDraft]
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
Return the structured object only."""


def _user_message(sources: str, answers: Answers, note: str) -> str:
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
        budget.caps["per_call_usd"] = max(budget.caps.get("per_call_usd", 0), SETUP_PER_CALL_USD)
        budget.check(llm.estimate(len(user) + len(SYSTEM), output_tokens=8000, model=model), PURPOSE)
    result, usage = llm.call(system=[{"type": "text", "text": SYSTEM}], user=user,
                             schema=Draft, model=model, effort="medium")
    if budget is not None:
        budget.record(usage, PURPOSE)
    return result
```

Check that `budget.caps` is a mutable dict on `Budget`. If it is not, build
the `Budget` in the wizard with
`caps={**caps, "per_call_usd": max(..., SETUP_PER_CALL_USD)}` instead, and
drop the mutation here.

Continue the module with `ground`:

```python
_YM = re.compile(r"^(\d{4})-(\d{2})$")


def ground(d: Draft, sources: str, answers: Answers) -> tuple[Draft, list[str]]:
    """Remove what the documents do not support. Deterministic: the model's
    output is a proposal, this is the check."""
    d = d.model_copy(deep=True)
    notes: list[str] = []
    corpus = sources + "\n" + json.dumps(answers.public())
    allowed = _digit_tokens(corpus)
    years = set(re.findall(r"\b(?:19|20)\d{2}\b", corpus))
    low = corpus.lower()

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

    kept = []
    for e in d.experience:
        if e.org.lower() not in low:
            notes.append(f"dropped the role at {e.org!r}: not named in your documents")
            continue
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
    for edu in d.education:
        edu.start = date_ok(edu.start, edu.institution)
    for p in d.projects:
        for attr in ("one_line", "three_line", "resume_line", "technical"):
            bad = unsourced(getattr(p, attr))
            if bad:
                notes.append(f"{p.name}: cleared {attr} — {', '.join(bad)} is not in your documents")
                setattr(p, attr, "" if attr == "technical" else ASK)
        if p.url and p.url.lower().removeprefix("https://").removeprefix("http://") not in low:
            notes.append(f"{p.name}: removed the link — it is not in your documents or answers")
            p.url = None
    return d, notes
```

Then `to_files`. It starts from the persona so every shape matches what the
rest of the code reads (`setup.profile_from` does the same):

```python
def _rx(phrase: str) -> str:
    from ..search import _pattern_for
    return _pattern_for(phrase)


def _bounded(phrase: str) -> str:
    return rf"(?<![A-Za-z0-9]){_rx(phrase)}(?![A-Za-z0-9])"


def _slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "place"


def to_files(d: Draft, answers: Answers) -> dict[str, dict]:
    from . import _clear_proof_assets, persona
    from ..search import country_of

    data = persona()
    names = {t.name for t in d.tracks}
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
                                "tracks": [t for t in p.tracks if t in names] or [d.default_track]}
                        for p in d.projects}
    data["skills"] = {g.group: g.items for g in d.skills}
    data["essays"] = {k: None for k in (data.get("essays") or {})} or None
    writing = data.get("writing") or {}
    writing["voice"] = d.voice
    writing.setdefault("letter", {})
    writing["letter"].update({"length": d.letter_length, "structure": d.letter_structure,
                              "proof_asset": {t.name: t.proof_asset for t in d.tracks}})
    writing["answers"] = {"why_role": d.why_role}
    writing["avoid"] = d.avoid
    data["writing"] = writing
    data.pop("_note", None)

    abroad = any(country_of(place) == "elsewhere" for place in answers.locations)
    search = {
        "rejects": {"seniority": [_rx(w) for w in d.reject_seniority],
                    "off_function": [_rx(w) for w in d.reject_functions],
                    "too_technical": [_rx(w) for w in d.reject_technical]},
        "geography": {_slug(p.label): {"label": p.label, "weight": p.weight,
                                       "patterns": [_rx(m) for m in p.match], "match_title": p.title}
                      for p in d.locations},
        "role_fit": [[_bounded(w.match), w.weight] for w in d.roles],
        "timing": [[_bounded(w.match), w.weight] for w in d.timing],
        "title_timing": [[_bounded(w.match), w.weight] for w in d.title_timing],
        "tracks": {"default": d.default_track,
                   "kinds": {t.name: {"resume": t.resume, "code_link": t.code_link,
                                      "keywords": [[k.phrase, k.weight] for k in t.keywords]}
                             for t in d.tracks}},
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
```

Two things to check before finishing:
1. Whether `_clear_proof_assets` is needed at all. It is not, because
   `proof_asset` is replaced wholesale. Remove the import if unused.
2. Read the reject block names in `search.defaults.yaml`. If they are not
   exactly `seniority`, `off_function` and `too_technical`, use the real
   names.

- [ ] **Step 5: Run the tests, then the full suite on both Pythons**

```bash
uv run pytest tests/test_setup_draft.py -v
uv run --python 3.11 pytest -q && uv run --python 3.13 pytest -q
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add src/apply/setup/draft.py tests/test_setup_draft.py tests/fixtures/setup tests/conftest.py
git commit -m "setup: Claude drafts a profile and a search; a deterministic pass keeps only what the documents support

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: The wizard, and `apply setup`

**Files:**
- Create: `src/apply/setup/wizard.py`, `tests/test_setup_wizard.py`
- Modify:
  - `src/apply/setup/__init__.py`: export `run_wizard`
  - `src/apply/cli.py`, `setup` command:
    - interactive by default runs the wizard
    - `--quick` is the old nine questions
    - `--step NAME` re-runs one step
    - `--persona` and `--non-interactive` are unchanged
  - `.gitignore` and `tests/test_fresh_clone.py` `USER_WRITES`: add
    `data/.setup_state.json`, `data/.setup_draft.json` and
    `data/.backup/x.yaml`
  - README "Commands" row for `setup`

**Interfaces:**
- Consumes:
  - `draft.*`, `extract.*`
  - `setup.copy_examples`, `setup.EXAMPLE_PROFILE`
  - `resolve.probe_slugs`, `resolve.resolve`, `Candidate.as_entry`
  - `secrets.store`, `secrets.lookup`, `llm.ping`
  - `budget.Budget`, `db.init_db`, `db.connect`
  - `schedule.install`, `schedule.Schedule`
  - `generate.tex_hint`, `generate.miktex_autoinstall`
- Produces:
  - `wizard.STEPS = ("toolchain", "key", "about", "documents", "draft", "review", "employers", "extras", "finish")`
  - `wizard.Asker`, a protocol with `text`, `secret`, `confirm`, `choice`,
    `edit` and `say`
  - `wizard.ConsoleAsker`
  - `wizard.run_wizard(asker, *, step=None, data=None) -> None`
  - The helpers `_ask_clean(asker, prompt, default=None) -> str` and
    `_write_file(data, rel, text, asker, *, example: Path | None = None) -> bool`

- [ ] **Step 1: Write the failing tests**

`tests/test_setup_wizard.py`:

```python
from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from apply.setup import wizard

FIX = Path(__file__).parent / "fixtures" / "setup"


class Script:
    """A scripted Asker. Each answer is keyed by a substring unique to one
    prompt; every scripted answer must be asked for."""

    def __init__(self, answers):
        self.answers = list(answers)
        self.said: list[str] = []

    def _next(self, prompt):
        for i, (needle, value) in enumerate(self.answers):
            if needle.lower() in prompt.lower():
                return self.answers.pop(i)[1]
        raise AssertionError(f"unscripted prompt: {prompt!r}")

    def text(self, prompt, default=None): return self._next(prompt)
    def secret(self, prompt): return self._next(prompt)
    def confirm(self, prompt, default=True): return self._next(prompt)
    def choice(self, prompt, options, default=None): return self._next(prompt)
    def edit(self, text): return None
    def say(self, markup): self.said.append(markup)


@pytest.fixture
def fake_api(monkeypatch):
    from apply import llm, resolve, secrets
    from apply.setup import draft as D

    stored = {}
    monkeypatch.setattr(secrets, "store", lambda n, v: stored.__setitem__(n, v.strip()))
    monkeypatch.setattr(secrets, "lookup", lambda n: stored.get(n))
    monkeypatch.setattr(llm, "ping", lambda: None)
    canned = D.Draft.model_validate(json.loads((FIX / "draft.json").read_text(encoding="utf-8")))
    monkeypatch.setattr(llm, "call", lambda **k: (canned, llm.Usage(k["model"], input_tokens=5000, output_tokens=2000)))
    monkeypatch.setattr(resolve, "probe_slugs", lambda name, verify_fn=None: None)
    return stored


def full_script(resume: Path):
    return [
        ("anthropic api key", "sk-ant-test"), ("monthly spending", "10"),
        ("kinds of roles", "backend software engineering"),
        ("internship, full-time, or both", "both"), ("where, most wanted first", "Seattle, WA"),
        ("is remote ok", True), ("firms you most want", "Acme Robotics"), ("to avoid", "sales"),
        ("linkedin url", ""), ("github url", ""), ("portfolio url", ""),
        ("should know about you", ""),
        ("authorized to work", True), ("sponsorship now", False), ("sponsorship in the future", False),
        ("currently a student", True), ("graduation date", "2027-05"),
        ("available full-time", ""), ("internship availability", "summer 2026"),
        ("phone, for your resume", "(555) 201-4477"), ("street address", ""), ("gpa", ""),
        ("path to your resume", str(resume)), ("path to a cover letter", ""), ("path to other writing", ""),
        ("identity: accept", "accept"), ("experience: accept", "accept"), ("projects: accept", "accept"),
        ("skills: accept", "accept"), ("writing: accept", "accept"), ("search: accept", "accept"),
        ("careers page for acme robotics", ""),
        ("job-alert mail", False), ("phone via ntfy", False), ("every morning", False),
    ]


def test_a_full_run_writes_exactly_the_expected_files(isolated_data_dir, fake_api):
    data = isolated_data_dir
    resume = data.parent / "resume.txt"
    resume.write_text((FIX / "resume.txt").read_text(encoding="utf-8"), encoding="utf-8")
    asker = Script(full_script(resume))
    wizard.run_wizard(asker, data=data)
    assert asker.answers == []
    assert fake_api["ANTHROPIC_API_KEY"] == "sk-ant-test"
    profile = yaml.safe_load((data / "profile.yaml").read_text(encoding="utf-8"))
    private = yaml.safe_load((data / "profile.private.yaml").read_text(encoding="utf-8"))
    search = yaml.safe_load((data / "search.yaml").read_text(encoding="utf-8"))
    assert profile["identity"]["legal_last"] == "Reyes"
    assert private["identity"]["phone"] == "(555) 201-4477"
    assert private["budget"]["monthly_usd"] == 10.0
    assert "swe" in search["tracks"]["kinds"]
    context = (data / "context" / "resume.md").read_text(encoding="utf-8")
    assert "201-4477" not in context and context.startswith("<!-- source: resume.txt")
    every_byte = "".join(p.read_text(encoding="utf-8", errors="ignore") for p in data.rglob("*") if p.is_file())
    assert "sk-ant" not in every_byte


def test_free_text_refuses_ssn():
    asker = Script([("kinds of roles", "analyst, my SSN is 123-45-6789"), ("kinds of roles", "analyst")])
    assert wizard._ask_clean(asker, "What kinds of roles are you after?") == "analyst"
    assert any("never stores" in s.lower() for s in asker.said)


def test_setup_backs_up_existing_files(isolated_data_dir):
    (isolated_data_dir / "profile.yaml").write_text("mine: true\n", encoding="utf-8")
    wizard._write_file(isolated_data_dir, "profile.yaml", "new: true\n", Script([("replace it", True)]))
    backups = list((isolated_data_dir / ".backup").rglob("profile.yaml"))
    assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == "mine: true\n"


def test_declining_the_overwrite_keeps_the_file(isolated_data_dir):
    (isolated_data_dir / "profile.yaml").write_text("mine: true\n", encoding="utf-8")
    wizard._write_file(isolated_data_dir, "profile.yaml", "new: true\n", Script([("replace it", False)]))
    assert (isolated_data_dir / "profile.yaml").read_text(encoding="utf-8") == "mine: true\n"


def test_example_employers_are_replaced_silently(isolated_data_dir):
    from apply.setup import EXAMPLE_PROFILE
    example = EXAMPLE_PROFILE.parent / "employers.example.yaml"
    (isolated_data_dir / "employers.yaml").write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
    assert wizard._write_file(isolated_data_dir, "employers.yaml", "employers: []\n", Script([]), example=example)
    assert (isolated_data_dir / "employers.yaml").read_text(encoding="utf-8") == "employers: []\n"


def test_one_step_can_be_rerun(isolated_data_dir, fake_api):
    wizard.run_wizard(Script([("anthropic api key", "sk-ant-2"), ("monthly spending", "")]),
                      step="key", data=isolated_data_dir)
    assert fake_api["ANTHROPIC_API_KEY"] == "sk-ant-2"


def test_unknown_step_exits(isolated_data_dir):
    with pytest.raises(SystemExit):
        wizard.run_wizard(Script([]), step="nope", data=isolated_data_dir)


def test_cli_quick_keeps_the_nine_questions(fresh):
    from apply.cli import app
    result = fresh.invoke(app, ["setup", "--help"])
    assert "--quick" in result.output and "--step" in result.output
```

The `isolated_data_dir` fixture name and type come from `tests/conftest.py`.
If it yields a `Path`, use it as written.

- [ ] **Step 2: Run them to see the failures**

```bash
uv run pytest tests/test_setup_wizard.py -v
```

Expected: FAIL.

- [ ] **Step 3: Implement `src/apply/setup/wizard.py`**

```python
"""`apply setup`: from a fresh clone to a configured pipeline, by asking.

Every step is resumable and re-runnable (`apply setup --step <name>`). Nothing
is written until the user accepts it; nothing existing is replaced without a
backup and a yes — except a file still byte-identical to its shipped example,
which was never the user's. The wizard writes configuration only: it cannot
move an application, and it never submits anything.
"""

from __future__ import annotations

import datetime as _dt
import getpass
import json
import shutil
from pathlib import Path
from typing import Protocol

import yaml

from . import draft as D
from . import extract

STEPS = ("toolchain", "key", "about", "documents", "draft", "review", "employers", "extras", "finish")


class Asker(Protocol):
    def text(self, prompt: str, default: str | None = None) -> str: ...
    def secret(self, prompt: str) -> str: ...
    def confirm(self, prompt: str, default: bool = True) -> bool: ...
    def choice(self, prompt: str, options: list[str], default: str | None = None) -> str: ...
    def edit(self, text: str) -> str | None: ...
    def say(self, markup: str) -> None: ...


class ConsoleAsker:
    def __init__(self, console):
        self.console = console

    def text(self, prompt, default=None):
        from rich.prompt import Prompt
        return Prompt.ask(prompt, default=default or "", console=self.console).strip()

    def secret(self, prompt):
        return getpass.getpass(f"{prompt}: ").strip()

    def confirm(self, prompt, default=True):
        from rich.prompt import Confirm
        return Confirm.ask(prompt, default=default, console=self.console)

    def choice(self, prompt, options, default=None):
        from rich.prompt import Prompt
        return Prompt.ask(prompt, choices=options, default=default, console=self.console)

    def edit(self, text):
        import click
        return click.edit(text, extension=".yaml")       # $EDITOR, or Notepad on Windows

    def say(self, markup):
        self.console.print(markup)


# ------------------------------------------------------------- files and state

def _state_path(data: Path) -> Path:
    return data / ".setup_state.json"


def _load_state(data: Path) -> dict:
    path = _state_path(data)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"done": []}


def _save_state(data: Path, state: dict) -> None:
    data.mkdir(parents=True, exist_ok=True)
    _state_path(data).write_text(json.dumps(state, indent=1), encoding="utf-8")


def _backup(data: Path, path: Path) -> Path:
    stamp = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    target = data / ".backup" / stamp / path.relative_to(data)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
    return target


def _write_file(data: Path, rel: str, text: str, asker: Asker, *, example: Path | None = None) -> bool:
    path = data / rel
    if path.exists():
        current = path.read_text(encoding="utf-8")
        untouched_example = example is not None and example.exists() and \
            current == example.read_text(encoding="utf-8")
        if current == text:
            return True
        if not untouched_example:
            if not asker.confirm(f"{rel} already exists. Back it up and replace it?", default=False):
                asker.say(f"[dim]kept your {rel}[/]")
                return False
            asker.say(f"[dim]backed up to {_backup(data, path)}[/]")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


def _write_yaml(data: Path, rel: str, body: dict, asker: Asker, **kw) -> bool:
    header = "# Written by `apply setup`. Edit freely; `apply doctor` checks it.\n"
    return _write_file(data, rel, header + yaml.safe_dump(body, sort_keys=False, allow_unicode=True), asker, **kw)


def _ask_clean(asker: Asker, prompt: str, default: str | None = None) -> str:
    """Free text, refusing anything that looks like an SSN or a date of birth."""
    while True:
        answer = asker.text(prompt, default)
        if not extract.contains_forbidden(answer):
            return answer
        asker.say("[bold red]APPLY never stores an SSN or a date of birth[/] — no field it fills "
                  "needs one. Leave it out and answer again.")
```

Then the step functions follow. Build them from the v1 plan's design,
adapted to this branch:

- **`_toolchain`:** print pdflatex found / `generate.tex_hint()`; warn when
  `generate.miktex_autoinstall() is False`.
- **`_key`:**
  - Explain that the key goes to the OS credential store.
  - Loop over `secret("Paste your Anthropic API key")`:
    - On an empty answer, reuse an existing `secrets.lookup(...)` if there is
      one; otherwise ask again.
    - On a value, `secrets.store(...)` then `llm.ping()`. On
      `LLMUnavailable`, show it and loop.
  - Then `text("Monthly spending ceiling in USD (Enter for $15)", "")`. Save
    `state["budget"] = {"monthly_usd": float(x)}` if a value was given.
- **`_about`:** the blurb and the direct questions. Use these prompts,
  which match the test needles:
  - "What kinds of roles are you after?"
  - "Internship, full-time, or both?" (a choice)
  - "Where, most wanted first? (comma-separated)"
  - "Is remote OK?"
  - "Firms you most want (comma-separated; Enter to skip)"
  - "Firms or kinds of work to avoid (Enter to skip)"
  - "LinkedIn URL (Enter to skip)", "GitHub URL (Enter to skip)",
    "Portfolio URL (Enter to skip)"
  - "Anything else a cover letter should know about you? (Enter to skip)"
  - "Are you authorized to work in the US?"
  - "Do you need visa sponsorship now?"
  - "Will you need sponsorship in the future?"
  - "Are you currently a student?"
  - "Graduation date, YYYY-MM (expected, or when you graduated)". Validate
    with `setup.check_grad_expected` and re-ask on error.
  - "When are you available full-time? (Enter to skip)"
  - "Internship availability (Enter to skip)"
  - "Phone, for your resume header (Enter to skip)",
    "Street address (Enter to skip)", "GPA (Enter to skip)"

  Every free-text answer goes through `_ask_clean`. Store
  `state["answers"] = asdict(D.Answers(...))`.
- **`_documents`:**
  - Ask "Path to your resume (PDF, DOCX, TXT or MD)" (required),
    "Path to a cover letter you liked (Enter to skip)", and "Path to other
    writing — a project write-up or portfolio page (Enter to skip)".
  - For each path: strip quotes, run `extract.read_document`, then
    `extract.redact(text, phone=answers.phone, address=answers.street_address)`.
    Show the word count, then
    `_write_file(data, f"context/{name}.md", f"<!-- source: {path.name}, imported by apply setup -->\n\n{clean}\n", asker)`.
    The names are `resume`, `cover_letter` and `other`. This matches the
    branch's `<!-- source: … -->` header convention in `context.pull_readme`.
  - `state["sources"] = "\n\n".join(texts)`.
- **`_draft(ctx, note="")`:**
  - `db.init_db()`, then `conn = db.connect()`. Hold `conn` in `ctx` and close
    it in `run_wizard`'s `finally`, because Windows cannot delete an open
    SQLite file.
  - Build the budget as
    `Budget(conn, caps={**budget.DEFAULTS, **(state.get("budget") or {})})`,
    then call `D.request(...)` and `D.ground(...)`.
  - Print each note as a yellow bullet.
  - Write `data/.setup_draft.json` (`model_dump_json`).
- **`_review`:**
  - Load the draft and `D.to_files(draft, answers)`.
  - For each `D.SECTIONS`, show the YAML of that section's view:
    - identity: `identity`, `links`, `education`, `availability`,
      `authorization`
    - experience: `experience`
    - projects: `projects`
    - skills: `skills`
    - writing: `writing`
    - search: the whole `search.yaml` dict
  - Ask with `choice(f"{section}: accept, edit, or redo with a note?", ["accept","edit","redo"], "accept")`:
    - **edit:** `asker.edit(yaml)`; if the result is not None, replace that
      section's keys with the loaded YAML.
    - **redo:** `_ask_clean("What should change?")`, then
      `_draft(ctx, note=f"[{section}] {note}")`, then rebuild `to_files` and
      replace only that section's keys.
  - After all sections:
    - `_write_yaml(data, "profile.yaml", files["profile.yaml"], asker)`
    - `_write_yaml(data, "search.yaml", files["search.yaml"], asker)`
    - Merge `files["profile.private.yaml"]` and `{"budget": {**budget.DEFAULTS, **state budget}}`
      into the existing `profile.private.yaml` (loaded if present, else `{}`),
      deep-merging with `profile.deep_merge` if it exists (grep), then
      `_write_yaml(..., example=EXAMPLE_PROFILE.parent / "profile.private.example.yaml")`.
    - `state["employers"] = [e.model_dump() for e in draft.employers]`.
  - Call `setup.copy_examples(data, EXAMPLE_PROFILE.parent)` first, so the
    files the rest of the app expects exist.
- **`_employers`:**
  - Search terms are the `match` of the first four draft roles; the default
    is `["analyst", "intern"]`.
  - For each named firm, `resolve.probe_slugs(name)`. If that fails, ask
    "Careers page for {name}? (URL, or Enter to skip)" and try
    `resolve.resolve(url, name=name)`, taking the first supported candidate
    with a count. If that fails too, add the firm to the unresolved list.
  - Write `{"employers": entries}` with
    `_write_yaml(data, "employers.yaml", ..., example=EXAMPLE_PROFILE.parent / "employers.example.yaml")`.
    Start `entries` from the existing file's entries only if that file is not
    the untouched example.
  - Explain each unresolved firm (the alert mail and `apply add --clipboard`
    still cover it).
- **`_extras`:**
  - "Read Handshake or LinkedIn job-alert mail from Gmail? (needs a Gmail app
    password)". On yes: ask the Gmail address and store it in private
    `imap.user`, then ask the app password with `secret` and
    `secrets.store("APPLY_IMAP_PASSWORD", pw.replace(" ", ""))`.
  - "Push notifications to your phone via ntfy.sh?". On yes: write
    `notify.ntfy_topic = "apply-" + secrets.token_urlsafe(12)`. Use the
    stdlib `secrets` module, imported as `import secrets as _random` to avoid
    the clash with `apply.secrets`. Print the topic.
  - "Run the discovery pass automatically every morning?". On yes, ask the
    time HH:MM, then
    `schedule.install(schedule.Schedule(hour, minute, project=generate.repo_root(), command="uv run apply run --notify --llm api"))`.
- **`_finish`:** the five commands, the never-submits sentence, and
  "Try it now: uv run apply discover --dry-run".

```python
RUNNERS = {...one per STEPS name...}


def run_wizard(asker: Asker, *, step: str | None = None, data: Path | None = None) -> None:
    from ..profile import data_dir

    data = data or data_dir()
    if step is not None and step not in RUNNERS:
        asker.say(f"[red]unknown step {step!r}[/]; one of: {', '.join(STEPS)}")
        raise SystemExit(2)
    state = _load_state(data)
    ctx = {"asker": asker, "data": data, "state": state}
    todo = [step] if step else [s for s in STEPS if s not in state["done"] or s == "finish"]
    try:
        for name in todo:
            RUNNERS[name](ctx)
            if name not in state["done"]:
                state["done"].append(name)
            _save_state(data, state)
    finally:
        if ctx.get("conn") is not None:
            ctx["conn"].close()
```

The state file holds answers and document text. It never holds a key or a
password, because `_key` and `_extras` write only through `secrets.store`.
The full-run test asserts this.

- [ ] **Step 4: Wire the CLI**

In `cli.setup`:
- Add `--quick` ("The nine questions, no API key needed") and
  `--step TEXT`.
- `--persona` and `--non-interactive` keep their current behaviour, exactly.
- `--quick` runs today's interactive `ask` path.
- Otherwise (the default, or `--step`), run:

```python
        from .setup.wizard import ConsoleAsker, run_wizard
        db.init_db()
        run_wizard(ConsoleAsker(console), step=step)
        return
```

Update the docstring: "Make this checkout yours. By default a guided setup
that reads your resume and asks what you are looking for (needs an Anthropic
API key); --quick asks nine questions instead; --persona writes the example
person."

**README Commands row for `setup`:**

```
`apply setup [--quick | --persona] [--step S]` | guided setup from your resume and goals; `--quick` without an API key
```

`.gitignore`:

```
# apply setup's working files.
data/.setup_state.json
data/.setup_draft.json
data/.backup/
```

Add `"data/.setup_state.json"`, `"data/.setup_draft.json"` and
`"data/.backup/20260101T000000/profile.yaml"` to `USER_WRITES`.

- [ ] **Step 5: Run the tests, then the full suite on both Pythons**

```bash
uv run pytest tests/test_setup_wizard.py tests/test_setup.py tests/test_fresh_clone.py -v
uv run --python 3.11 pytest -q && uv run --python 3.13 pytest -q
```

Expected: all pass.

- [ ] **Step 6: Smoke test, with no key needed**

```bash
APPLY_DATA_DIR=$(mktemp -d) uv run apply setup --step toolchain
APPLY_DATA_DIR=$(mktemp -d) uv run apply setup --non-interactive
```

Expected: both exit 0.

- [ ] **Step 7: Commit**

```bash
git add src/apply/setup src/apply/cli.py .gitignore tests/test_setup_wizard.py tests/test_fresh_clone.py README.md
git commit -m "apply setup reads your resume and asks what you want, then configures everything — after you approve it

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Bootstrap scripts

**Files:**
- Create: `scripts/install.ps1`, `scripts/install.sh`
- Test: `tests/test_portability.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def test_install_scripts_exist_and_end_in_setup():
    ps1 = (ROOT / "scripts" / "install.ps1").read_text(encoding="utf-8")
    sh = (ROOT / "scripts" / "install.sh").read_text(encoding="utf-8")
    for script in (ps1, sh):
        assert "uv sync" in script and "apply setup" in script
    assert "winget install" in ps1 and "MiKTeX.MiKTeX" in ps1 and "AutoInstall=1" in ps1
    assert "astral.sh/uv/install.ps1" in ps1
```

- [ ] **Step 2: Run it to see the failure**

```bash
uv run pytest tests/test_portability.py -v -k install
```

Expected: FAIL.

- [ ] **Step 3: Write the scripts**

`scripts/install.ps1`:

```powershell
# APPLY setup for Windows. From the folder you cloned into:
#   powershell -ExecutionPolicy Bypass -File scripts\install.ps1
# Safe to re-run: anything already installed is skipped.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

function Have($name) { [bool](Get-Command $name -ErrorAction SilentlyContinue) }
function Ask($q) { (Read-Host "$q [Y/n]") -notmatch '^[nN]' }
function Refresh-Path {
  $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
              [Environment]::GetEnvironmentVariable("Path", "User")
}

if (-not (Have winget)) {
  Write-Host "winget is missing. Install 'App Installer' from the Microsoft Store, then re-run." -ForegroundColor Red
  exit 1
}
if (-not (Have git) -and (Ask "Install Git?")) {
  winget install --id Git.Git -e --accept-package-agreements --accept-source-agreements
  Refresh-Path
}
if (-not (Have uv)) {
  if (Ask "Install uv (the Python manager APPLY uses)?") {
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    Refresh-Path
  } else { Write-Host "uv is required."; exit 1 }
}
if (-not (Have pdflatex) -and (Ask "Install MiKTeX (typesets the PDFs; about 300 MB)?")) {
  winget install --id MiKTeX.MiKTeX -e --accept-package-agreements --accept-source-agreements
  Refresh-Path
}
if (Have initexmf) {
  # Without this MiKTeX opens a dialog for each missing package, and a
  # scheduled run waits forever for a click.
  initexmf --set-config-value=[MPM]AutoInstall=1 | Out-Null
}

uv sync
uv run apply setup
```

`scripts/install.sh`:

```bash
#!/usr/bin/env bash
# APPLY setup for macOS and Linux. From the folder you cloned into:  bash scripts/install.sh
set -euo pipefail
cd "$(dirname "$0")/.."

ask() { read -r -p "$1 [Y/n] " reply; [[ ! "$reply" =~ ^[nN] ]]; }

if ! command -v uv >/dev/null; then
  if ask "Install uv (the Python manager APPLY uses)?"; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    export PATH="$HOME/.local/bin:$PATH"
  else echo "uv is required."; exit 1; fi
fi
if ! command -v pdflatex >/dev/null; then
  echo "No TeX yet — letters can be written but not typeset. $(uv run python -c 'from apply.generate import tex_hint; print(tex_hint())' 2>/dev/null || true)"
fi

uv sync
uv run apply setup
```

```bash
chmod +x scripts/install.sh
```

Check `pyproject.toml`: if `anthropic` is an optional extra on this branch
(`[project.optional-dependencies]`), both scripts must run
`uv sync --all-extras`, because the wizard needs the SDK. Update the test's
`"uv sync"` check accordingly. It still matches.

- [ ] **Step 4: Run the suite**

```bash
uv run pytest -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add scripts tests/test_portability.py
git commit -m "One command to install and set up, on Windows and on macOS/Linux

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Windows in CI

**Files:**
- Modify: `.github/workflows/tests.yml`

- [ ] **Step 1: Edit the workflow**

1. **Job `test`:** set `os: [ubuntu-latest, macos-latest, windows-latest]`.
2. Add a step after Install, so the PDF tests run on one Windows leg:

```yaml
      - name: TeX (Windows, one leg)
        if: runner.os == 'Windows' && matrix.python == '3.13'
        shell: pwsh
        run: |
          choco install miktex --no-progress -y
          $bin = "C:\Program Files\MiKTeX\miktex\bin\x64"
          echo $bin | Out-File -FilePath $env:GITHUB_PATH -Encoding utf8 -Append
          & "$bin\initexmf.exe" --admin --set-config-value=[MPM]AutoInstall=1
          & "$bin\miktex.exe" --admin packages update-package-database
```

3. **Job `smoke`:** set `os: [ubuntu-latest, macos-latest, windows-latest]`
   and add `defaults: run: shell: bash` to the job, so `test -f`/`test -z`
   work on Windows (Git Bash).
4. Keep `apply schedule --show`, which Task 4 made work on Windows.
5. Make sure `uv sync` installs the anthropic SDK if it is an extra, since
   `apply setup --help` imports the wizard lazily. It should, so check that
   the `--help` path does not import `anthropic` at module import.

- [ ] **Step 2: Lint the YAML locally**

```bash
uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/tests.yml', encoding='utf-8')); print('ok')"
```

Expected: `ok`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/tests.yml
git commit -m "CI on Windows: the suite (with MiKTeX on one leg) and the quick start

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Pushing to run CI is an outward-facing action that the controller handles
with the owner at the end. Do not push.

---

### Task 13: Docs — README, AGENTS.md, CLAUDE.md

**Files:**
- Modify: `README.md`, `CLAUDE.md`, `docs/linkedin-alerts.md` (the owner's
  city at lines 55 and 60 becomes a generic example city)
- Create: `AGENTS.md`
- Test: `tests/test_portability.py` (append)

- [ ] **Step 1: Write the failing test**

```python
def test_docs_point_new_users_at_setup_on_every_os():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    assert "## Start here" in readme
    assert "scripts\\install.ps1" in readme and "scripts/install.sh" in readme
    assert "Windows" in readme and "Task Scheduler" in readme
    assert "apply setup" in agents and "uv run" in agents and "Never" in agents
```

- [ ] **Step 2: Run it to see the failure**

```bash
uv run pytest tests/test_portability.py -v -k docs
```

Expected: FAIL.

- [ ] **Step 3: Edit**

**README:**
1. Add a `## Start here` section near the top, before the existing quick
   start at README.md:82. It holds the two install commands (PowerShell and
   bash), one paragraph on what `apply setup` asks and writes, the cost
   (about $0.10–0.60 for setup, at the draft model's prices), and
   `uv run apply setup --step about` / `--step employers` for re-running
   parts.
2. Remove the "What a clone gets today" caveat (README.md:88-93) if it says
   the branch is unmerged, since this is now the branch being shipped.
3. In the key-storage block (README.md:126-132), add the Windows line: "the
   key is stored in Windows Credential Manager by `apply setup`". Mention
   `secrets.store` for every OS.
4. In "Running unattended" (README.md:499), add Task Scheduler.
5. Wherever the README says `touch data/HALT`, add "(on Windows: `type nul >
   data\HALT`)".

**`AGENTS.md`:**

```markdown
# APPLY — instructions for AI coding agents (Cursor, Codex, Claude Code)

First time here? Set it up before anything else:

    Windows:  powershell -ExecutionPolicy Bypass -File scripts\install.ps1
    macOS / Linux:  bash scripts/install.sh
    Already installed:  uv run apply setup

If `data/profile.yaml` does not exist, tell the user to run `uv run apply setup` —
do not write their profile yourself.

## Never
- Submit an application. No automated POST, click, or scheduled submission.
- Scrape or authenticate against Handshake.
- Store credentials, SSN, DOB, or bank details in any file.
- Promote an application to `ready` or `submitted` without an explicit human action.
- Write a fact into a generated document that is not present in profile.yaml.

## Always
- Use `uv` for everything: `uv run apply ...`, `uv run pytest -q`, `uv add ...`. Never bare pip.
- Pass `encoding="utf-8"` to every text read and write (Windows defaults to cp1252).
- Tests never call the API (tests/conftest.py enforces it).

CLAUDE.md and README.md hold the full rules and the reasons for them.
```

**`CLAUDE.md`:** under "Conventions", add:

```
- Platform code lives in its seam: secrets.py (keys), schedule.py (launchd,
  systemd, cron, Task Scheduler), cli.read_clipboard, notify.banner,
  generate.tex_hint, host.open_path. Pass encoding="utf-8" to every text
  read and write.
- Tracks and the gate's limits are configuration (search.defaults.yaml,
  overridden by data/search.yaml). The defaults are the owner's and must not
  drift: the frozen corpora say so.
```

- [ ] **Step 4: Run the suite and commit**

```bash
uv run pytest -q
git add README.md AGENTS.md CLAUDE.md docs/linkedin-alerts.md tests/test_portability.py
git commit -m "Docs: start here on every OS, and AGENTS.md for Cursor

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: The starter export

**Files:**
- Create: `scripts/export_starter.py`, `tests/test_export.py`

**Interfaces:**
- Produces:
  - `export(target: Path, repo: Path) -> list[str]`
  - `biography_in(paths) -> list[str]`
  - `EXCLUDE_PREFIXES = ("docs/superpowers/", ".reviews/")`
  - `AUTHORSHIP_LINES`: lines that may name the author. These are the LICENSE
    copyright, the repository URL in `pyproject.toml` and `README.md`, the
    `LEGACY_LABELS` line in `schedule.py`, and the userscript `@namespace`.

- [ ] **Step 1: Write the failing tests**

```python
"""The starter repo a friend clones: every tracked file, none of the owner's life."""

from __future__ import annotations

import runpy
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
export = runpy.run_path(str(REPO / "scripts" / "export_starter.py"))


def test_the_export_deny_list_covers_the_tests_one():
    import importlib.util
    spec = importlib.util.spec_from_file_location("t", REPO / "tests" / "test_setup.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert set(mod.AUTHORS_BIOGRAPHY) <= set(export["BIOGRAPHY"])


def test_export_builds_a_clean_single_commit_repo(tmp_path):
    target = tmp_path / "apply-starter"
    copied = export["export"](target, REPO)
    assert "src/apply/cli.py" in copied
    assert not any(p.startswith(("docs/superpowers/", ".reviews/")) for p in copied)
    assert not (target / "data" / "profile.yaml").exists()
    assert (target / "data" / "profile.example.yaml").exists()
    log = subprocess.run(["git", "log", "--oneline"], cwd=target, capture_output=True,
                         text=True, encoding="utf-8", check=True)
    assert len(log.stdout.strip().splitlines()) == 1
    files = [p for p in target.rglob("*") if p.is_file() and ".git" not in p.parts]
    assert export["biography_in"](files) == []
```

`test_setup.py` lives in `tests/`, so loading it this way runs its
module-level code. If that pulls fixtures, copy the tuple out with a regex
over the file's text instead.

- [ ] **Step 2: Run them to see the failures**

```bash
uv run pytest tests/test_export.py -v
```

Expected: FAIL with `FileNotFoundError`.

- [ ] **Step 3: Implement `scripts/export_starter.py`**

```python
"""Build the starter repo: every tracked file, none of the author's life.

    uv run python scripts/export_starter.py <target-dir>

Authorship stays (the LICENSE, the repository URL); biography does not. The
check is the same word list tests/test_setup.py holds the persona to, run over
every file that ships.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Iterable

EXCLUDE_PREFIXES = ("docs/superpowers/", ".reviews/")
BIOGRAPHY = ("ajai", "upadhyaya", "vcu", "virginia commonwealth", "university of virginia",
             "ohcamel", "richmond", "charlottesville", "bloomberg", "morningstar", "wrds")
#: Lines that may name the author: attribution, not biography.
AUTHORSHIP_LINES = (re.compile(r"^Copyright", re.I), re.compile(r"github\.com/ajaiupadhyaya/apply"),
                    re.compile(r"LEGACY_LABELS"), re.compile(r"@namespace"))


def biography_in(paths: Iterable[Path]) -> list[str]:
    hits = []
    for path in paths:
        if path.name == "export_starter.py" or path.name == "test_setup.py":
            continue                       # the files that hold the list itself
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for n, line in enumerate(text.splitlines(), 1):
            low = line.lower()
            if any(w in low for w in BIOGRAPHY) and not any(p.search(line) for p in AUTHORSHIP_LINES):
                hits.append(f"{path}:{n}")
    return hits


def export(target: Path, repo: Path) -> list[str]:
    if target.exists() and any(target.iterdir()):
        raise SystemExit(f"{target} is not empty")
    listed = subprocess.run(["git", "ls-files", "-z"], cwd=repo, capture_output=True, check=True)
    names = [n for n in listed.stdout.decode("utf-8").split("\0")
             if n and not n.startswith(EXCLUDE_PREFIXES)]
    hits = biography_in(repo / n for n in names)
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
```

Substring matching is loose. For example, "bloomberg" in a docs mention of
the Bloomberg Terminal, or "wrds" inside another word, would match. Run the
export test, read every hit, and decide each one:
- If the hit is genuinely about the owner, fix the file.
- If it is a generic mention (a product name in the classify keywords or the
  gate vocabulary), add a targeted entry to `AUTHORSHIP_LINES`, or narrow the
  match to word boundaries (`re.search(rf"\b{re.escape(w)}\b", low)`).

Prefer word boundaries. Record each decision in the report.

- [ ] **Step 4: Run the full suite**

```bash
uv run --python 3.11 pytest -q && uv run --python 3.13 pytest -q
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add scripts/export_starter.py tests/test_export.py
git commit -m "Export a clean starter repo: one commit, none of the author's biography

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Building and publishing the starter repo, and inviting the friend, are
outward-facing. The controller does them with the owner's go-ahead.

---

## Self-Review

1. **Spec coverage**, using the addendum's mapping:
   - **Part 1 (Windows):**
     - 1.1 → Task 2
     - 1.2 → Task 3
     - 1.3 → Task 4
     - 1.4 → Task 1
     - 1.5 → Task 2
     - 1.6 → Task 11
     - 1.7 → Task 12
   - **Part 2 (configuration):**
     - 2.1 → already done on this branch, plus the gitignore entries in
       Task 10
     - 2.2 → Task 5
     - 2.3 → Task 6 (the rest was already done)
     - 2.4 → Task 7 for the resolve search terms, Task 14 for the export
       deny-list, Task 13 for the docs city
   - **Part 3 (wizard):** Tasks 8, 9 and 10; the IMAP user is in Task 3.
   - **Part 4 (handover):** export → Task 14, docs → Task 13.
2. **Placeholder scan:** one deliberate instruction remains, Task 5's
   `_letter_kwargs`. It tells the implementer to read `generate.Letter`; the
   finished test must not raise. Task 10's step functions are specified as
   behaviour plus exact prompts rather than code, because they are thin glue
   over Tasks 7–9 and the branch's existing helpers. The test pins every
   prompt.
3. **Type consistency:**
   - `TrackSpec`, `SearchConfig.track()`, `.tracks`, `.default_track` and
     `.limits` are used consistently across Tasks 5, 6, 9 and 10.
   - `secrets.store`/`lookup` and `llm.ping` (Task 3) are used in Task 10.
   - `resolve.probe_slugs`/`as_entry` (Task 7) are used in Task 10.
   - `draft.Answers`/`Draft`/`ground`/`to_files`/`request` (Task 9) are used
     in Task 10.
4. **Review Focus:** each of the five items names its test and owning task.
