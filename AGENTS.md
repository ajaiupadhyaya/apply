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
