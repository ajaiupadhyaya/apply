"""Where a secret comes from, in one place and one order.

The order is: the environment, then the OS credential store through keyring
(Windows Credential Manager, the macOS Keychain, or a Secret Service). A scheduled run is why the store
lookups exist at all — a systemd timer and a cron line read no profile of the
user's at all, and the launchd agent runs `zsh -lc`, which reads ~/.zprofile
but not ~/.zshrc, where the export usually is. Either way the variable is
simply absent at 06:30.

Nothing here writes a secret to a file: `store` hands it to the OS credential
store through keyring (Windows Credential Manager, the macOS Keychain, or a
Secret Service), and no value is ever logged.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from importlib.util import find_spec as _find_spec

#: How to store a secret so that an unattended run can find it, per platform.
INSTRUCTIONS = {
    "darwin": 'security add-generic-password -U -a "$USER" -s {name} -w',
    "linux": ("keyring set apply {name}        # needs a Secret Service running\n"
              "  or: export {name}=...        # in the shell that runs apply"),
    "windows": "uv run apply setup --step {step}",
    "other": "export {name}=...",
}


def platform_key() -> str:
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform == "win32":
        return "windows"
    return "linux" if sys.platform.startswith("linux") else "other"


def how_to_store(name: str) -> str:
    """The line to tell the user when a secret is missing."""
    step = "extras" if name == "APPLY_IMAP_PASSWORD" else "key"
    return INSTRUCTIONS[platform_key()].format(name=name, step=step)


def _from_keychain(name: str) -> str | None:
    """The macOS login Keychain. Absent everywhere else."""
    if sys.platform != "darwin" or not shutil.which("security"):
        return None
    result = subprocess.run(
        ["security", "find-generic-password", "-a", os.environ.get("USER", ""),
         "-s", name, "-w"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    return (result.stdout.strip() or None) if result.returncode == 0 else None


def _from_keyring(name: str) -> str | None:
    """The OS credential store, through keyring."""
    if _find_spec("keyring") is None:           
        return None
    try:
        import keyring

        return keyring.get_password("apply", name) or None
    except Exception:                             # noqa: BLE001 — locked or absent backend
        return None


def lookup(name: str) -> str | None:
    """The secret, or None. Environment first, then the platform's store."""
    for source in (lambda n: os.environ.get(n), _from_keychain, _from_keyring):
        value = source(name)
        if value and value.strip():
            return value.strip()
    return None


def store(name: str, value: str) -> None:
    """Hand a secret to the OS credential store. Never to a file, never logged.

    Same service and username `_from_keyring` reads, so `lookup` finds it from a
    terminal and from a scheduled run alike."""
    value = (value or "").strip()
    if not value:
        raise ValueError(f"refusing to store an empty {name}")
    import keyring

    keyring.set_password("apply", name, value)
