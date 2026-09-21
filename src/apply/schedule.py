"""Running the pass on a schedule, with launchd.

launchd rather than cron because it is what macOS actually supervises: it
survives reboots, it does not need the Terminal open, and it will catch up a
missed run after the laptop wakes.

The job runs through `zsh -lc` so that PATH is set (uv lives under Homebrew).
It does NOT rely on the shell for the API key: a non-interactive login shell
never reads ~/.zshrc, so the key exported there is absent under launchd. The
app reads the key from the Keychain itself (llm._keychain_key), which works
here and everywhere else.

Installing a LaunchAgent is persistent configuration on someone's machine, so
nothing here installs anything on its own — `--show` prints exactly what would
be written, and `--install` is a separate, explicit act.
"""

from __future__ import annotations

import plistlib
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

LABEL = "com.ajaiupadhyaya.apply"


def agents_dir() -> Path:
    return Path.home() / "Library" / "LaunchAgents"


def plist_path() -> Path:
    return agents_dir() / f"{LABEL}.plist"


@dataclass(slots=True)
class Schedule:
    hour: int = 6
    minute: int = 30
    project: Path = Path.cwd()
    command: str = "uv run apply run --notify"

    def as_plist(self) -> dict:
        out = self.project / "out"
        return {
            "Label": LABEL,
            # A login shell for PATH. The key comes from the Keychain, read by
            # the app itself — ~/.zshrc is never sourced by a non-interactive shell.
            "ProgramArguments": [
                "/bin/zsh", "-lc",
                f"cd {_quote(self.project)} && {self.command}",
            ],
            "StartCalendarInterval": {"Hour": self.hour, "Minute": self.minute},
            "StandardOutPath": str(out / "run.log"),
            "StandardErrorPath": str(out / "run.err"),
            # Do not fire on login: a laptop opened at midnight should not kick
            # off a discovery pass before anyone has had coffee.
            "RunAtLoad": False,
            "ProcessType": "Background",
        }

    def render(self) -> str:
        return plistlib.dumps(self.as_plist()).decode()


def _quote(path: Path) -> str:
    text = str(path)
    return f'"{text}"' if " " in text else text


def install(schedule: Schedule) -> Path:
    if sys.platform != "darwin":
        raise RuntimeError("launchd is macOS only.")
    agents_dir().mkdir(parents=True, exist_ok=True)
    (schedule.project / "out").mkdir(parents=True, exist_ok=True)
    path = plist_path()
    path.write_bytes(plistlib.dumps(schedule.as_plist()))
    subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
    result = subprocess.run(["launchctl", "load", str(path)], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "launchctl load failed")
    return path


def remove() -> bool:
    path = plist_path()
    if not path.exists():
        return False
    subprocess.run(["launchctl", "unload", str(path)], capture_output=True)
    path.unlink()
    return True


def status() -> dict:
    path = plist_path()
    if not path.exists():
        return {"installed": False}
    data = plistlib.loads(path.read_bytes())
    when = data.get("StartCalendarInterval", {})
    listed = subprocess.run(["launchctl", "list", LABEL], capture_output=True, text=True)
    return {
        "installed": True,
        "path": str(path),
        "at": f"{when.get('Hour', 0):02d}:{when.get('Minute', 0):02d}",
        "loaded": listed.returncode == 0,
        "command": (data.get("ProgramArguments") or ["", "", ""])[-1],
        "log": data.get("StandardOutPath", ""),
    }
