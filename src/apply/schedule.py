"""Running the pass on a schedule, on whatever supervises this machine.

Three backends, one interface. macOS gets launchd, because it is what the OS
actually supervises: it survives reboots, it does not need a Terminal open, and
it catches up a missed run after the laptop wakes. Linux gets a systemd user
timer for the same reasons — `Persistent=true` is launchd's catch-up — and
falls back to cron on a box without systemd.

Every job runs through a login shell so that PATH is set (uv is rarely on the
default one). None of them relies on that shell for a secret: a non-interactive
login shell never reads ~/.zshrc or ~/.bashrc, so a key exported there is simply
absent at 06:30. The app reads its secrets itself, through `apply.secrets`.

Installing a timer is persistent configuration on someone's machine, so nothing
here installs anything on its own — `--show` prints exactly what would be
written, and `--install` is a separate, explicit act.
"""

from __future__ import annotations

import plistlib
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

#: The launchd label, and the name of the plist under ~/Library/LaunchAgents.
#: Neutral on purpose: this repository is public, and an agent that runs every
#: morning on a stranger's laptop should not be named after its author.
LABEL = "apply.daily"

#: Labels earlier versions installed. A rename alone would orphan one of those
#: agents — still loaded, still running at 06:30, and invisible to `--remove` —
#: so install and remove both retire whatever they find under an old name.
LEGACY_LABELS = ("com.ajaiupadhyaya.apply",)

#: The systemd unit name, and the tag on the cron line.
UNIT = "apply"


def _run(argv: list[str], stdin: str | None = None):
    """Every call to launchctl, systemctl or crontab, in one interceptable place."""
    return subprocess.run(argv, input=stdin, capture_output=True, text=True)


def _ok(result) -> bool:
    return getattr(result, "returncode", 1) == 0


def _quote(path: Path) -> str:
    text = str(path)
    return f'"{text}"' if " " in text else text


@dataclass(slots=True)
class Schedule:
    """When the pass runs, from where, and as what command.

    A plan does not render itself. What it looks like — a plist, two systemd
    units, one crontab line — is the supervisor's business, and `backend()` is
    the single place that decides which supervisor this machine has.
    """

    hour: int = 6
    minute: int = 30
    project: Path = Path.cwd()
    command: str = "uv run apply run --notify"

    @property
    def at(self) -> str:
        return f"{self.hour:02d}:{self.minute:02d}"

    @property
    def log(self) -> Path:
        return self.project / "out" / "run.log"

    def shell_command(self) -> str:
        return f"cd {_quote(self.project)} && {self.command}"


# ------------------------------------------------------------------ launchd

class LaunchdBackend:
    """macOS. A LaunchAgent in ~/Library/LaunchAgents."""

    def agents_dir(self) -> Path:
        return Path.home() / "Library" / "LaunchAgents"

    def plist_path(self, label: str | None = None) -> Path:
        return self.agents_dir() / f"{label or LABEL}.plist"

    def agents(self) -> list[tuple[str, Path]]:
        """Every agent this project has installed here, current label first."""
        return [(label, self.plist_path(label))
                for label in (LABEL, *LEGACY_LABELS)
                if self.plist_path(label).exists()]

    def _retire_legacy(self) -> list[str]:
        """Unload and delete any agent left behind under an older label."""
        retired = []
        for label in LEGACY_LABELS:
            path = self.plist_path(label)
            if path.exists():
                _run(["launchctl", "unload", str(path)])
                path.unlink()
                retired.append(label)
        return retired

    def as_plist(self, schedule: Schedule) -> dict:
        return {
            "Label": LABEL,
            # A login shell for PATH. Secrets come from the Keychain, read by
            # the app itself — ~/.zshrc is never sourced by a non-interactive shell.
            "ProgramArguments": ["/bin/zsh", "-lc", schedule.shell_command()],
            "StartCalendarInterval": {"Hour": schedule.hour, "Minute": schedule.minute},
            "StandardOutPath": str(schedule.log),
            "StandardErrorPath": str(schedule.project / "out" / "run.err"),
            # Do not fire on login: a laptop opened at midnight should not kick
            # off a discovery pass before anyone has had coffee.
            "RunAtLoad": False,
            "ProcessType": "Background",
        }

    def render(self, schedule: Schedule) -> str:
        return plistlib.dumps(self.as_plist(schedule)).decode()

    def install(self, schedule: Schedule) -> Path:
        if sys.platform != "darwin":
            raise RuntimeError("launchd is macOS only.")
        self.agents_dir().mkdir(parents=True, exist_ok=True)
        (schedule.project / "out").mkdir(parents=True, exist_ok=True)
        # Before ours is loaded, so the machine never runs two passes a morning.
        self._retire_legacy()
        path = self.plist_path()
        path.write_bytes(plistlib.dumps(self.as_plist(schedule)))
        _run(["launchctl", "unload", str(path)])
        result = _run(["launchctl", "load", str(path)])
        if not _ok(result):
            raise RuntimeError(getattr(result, "stderr", "").strip() or "launchctl load failed")
        return path

    def remove(self) -> bool:
        removed = bool(self._retire_legacy())
        path = self.plist_path()
        if path.exists():
            _run(["launchctl", "unload", str(path)])
            path.unlink()
            removed = True
        return removed

    def status(self) -> dict:
        found = self.agents()
        if not found:
            return {"installed": False}
        label, path = found[0]
        data = plistlib.loads(path.read_bytes())
        when = data.get("StartCalendarInterval", {})
        return {
            "installed": True,
            "path": str(path),
            "at": f"{when.get('Hour', 0):02d}:{when.get('Minute', 0):02d}",
            "loaded": _ok(_run(["launchctl", "list", label])),
            "command": (data.get("ProgramArguments") or ["", "", ""])[-1],
            "log": data.get("StandardOutPath", ""),
        }


# ------------------------------------------------------------------ systemd

SERVICE = """[Unit]
Description=apply: one unattended pass

[Service]
Type=oneshot
WorkingDirectory={project}
ExecStart=/bin/sh -lc '{command}'
"""

TIMER = """[Unit]
Description=apply: {at} every day

[Timer]
OnCalendar=*-*-* {at}:00
Persistent=true

[Install]
WantedBy=timers.target
"""


class SystemdBackend:
    """Linux with systemd. A user timer, so it needs no root and no unit outside
    the user's own ~/.config."""

    def unit_dir(self) -> Path:
        return Path.home() / ".config" / "systemd" / "user"

    def units(self, schedule: Schedule) -> dict[str, str]:
        return {
            f"{UNIT}.service": SERVICE.format(project=schedule.project,
                                              command=schedule.command),
            f"{UNIT}.timer": TIMER.format(at=schedule.at),
        }

    def render(self, schedule: Schedule) -> str:
        return "\n".join(f"# {name}\n{text}"
                         for name, text in self.units(schedule).items())

    def install(self, schedule: Schedule) -> Path:
        directory = self.unit_dir()
        directory.mkdir(parents=True, exist_ok=True)
        for name, text in self.units(schedule).items():
            (directory / name).write_text(text)
        _run(["systemctl", "--user", "daemon-reload"])
        _run(["systemctl", "--user", "enable", "--now", f"{UNIT}.timer"])
        return directory / f"{UNIT}.timer"

    def remove(self) -> bool:
        directory = self.unit_dir()
        found = [directory / f"{UNIT}.timer", directory / f"{UNIT}.service"]
        if not any(path.exists() for path in found):
            return False
        _run(["systemctl", "--user", "disable", "--now", f"{UNIT}.timer"])
        for path in found:
            path.unlink(missing_ok=True)
        _run(["systemctl", "--user", "daemon-reload"])
        return True

    def status(self) -> dict:
        timer = self.unit_dir() / f"{UNIT}.timer"
        service = self.unit_dir() / f"{UNIT}.service"
        if not timer.exists():
            return {"installed": False}
        when = re.search(r"OnCalendar=\*-\*-\* (\d{2}:\d{2})", timer.read_text())
        command = re.search(r"ExecStart=/bin/sh -lc '(.*)'",
                            service.read_text() if service.exists() else "")
        return {
            "installed": True,
            "path": str(timer),
            "at": when.group(1) if when else "",
            "loaded": _ok(_run(["systemctl", "--user", "is-enabled", f"{UNIT}.timer"])),
            "command": command.group(1) if command else "",
            "log": f"journalctl --user -u {UNIT}.service",
        }


# --------------------------------------------------------------------- cron

class CronBackend:
    """Linux without systemd, and anywhere else with a crontab. One line, tagged,
    and no line without that tag is ever read as ours or written over."""

    MARKER = f"# {UNIT}"

    def render(self, schedule: Schedule) -> str:
        return (f"{schedule.minute} {schedule.hour} * * * {schedule.shell_command()} "
                f">> {_quote(schedule.log)} 2>&1  {self.MARKER}")

    def _read(self) -> str:
        result = _run(["crontab", "-l"])
        return getattr(result, "stdout", "") if _ok(result) else ""

    def _write(self, text: str) -> None:
        result = _run(["crontab", "-"], text)
        if not _ok(result):
            raise RuntimeError(getattr(result, "stderr", "").strip() or "crontab rejected the table")

    def _others(self) -> list[str]:
        return [line for line in self._read().splitlines() if self.MARKER not in line]

    def _mine(self) -> str | None:
        for line in self._read().splitlines():
            if self.MARKER in line:
                return line
        return None

    def install(self, schedule: Schedule) -> str:
        schedule.log.parent.mkdir(parents=True, exist_ok=True)
        line = self.render(schedule)
        self._write("\n".join([*self._others(), line]) + "\n")
        return line

    def remove(self) -> bool:
        if self._mine() is None:
            return False
        others = self._others()
        self._write("\n".join(others) + "\n" if others else "")
        return True

    def status(self) -> dict:
        line = self._mine()
        if line is None:
            return {"installed": False}
        fields = line.split(maxsplit=5)
        command = fields[5] if len(fields) > 5 else ""
        return {
            "installed": True,
            "path": "crontab (crontab -l)",
            "at": f"{int(fields[1]):02d}:{int(fields[0]):02d}",
            "loaded": True,                    # a line in the crontab is running
            "command": command.split(f"  {self.MARKER}")[0],
            "log": "wherever the line redirects; out/run.log by default",
        }


def backend(platform: str | None = None):
    """The supervisor for a platform: launchd, systemd, or cron."""
    name = platform or sys.platform
    if name.startswith("darwin"):
        return LaunchdBackend()
    if name.startswith("linux"):
        return SystemdBackend() if shutil.which("systemctl") else CronBackend()
    raise RuntimeError("no scheduler for this platform; run `apply run` from your own cron")


def install(schedule: Schedule):
    return backend().install(schedule)


def remove() -> bool:
    return backend().remove()


def status() -> dict:
    return backend().status()


def agents_dir() -> Path:
    return LaunchdBackend().agents_dir()


def plist_path() -> Path:
    return LaunchdBackend().plist_path()
