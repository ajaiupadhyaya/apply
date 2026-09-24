"""Where a secret comes from, in one place and one order.

The order is: the environment, then the macOS Keychain, then a Secret Service
keyring if the user happens to have one. A scheduled run is why the store
lookups exist at all — a systemd timer and a cron line read no profile of the
user's at all, and the launchd agent runs `zsh -lc`, which reads ~/.zprofile
but not ~/.zshrc, where the export usually is. Either way the variable is
simply absent at 06:30.

Nothing here writes a secret anywhere, and no value is ever logged. `keyring`
is not a dependency of this project: it is reached through `find_spec`, so the
import is attempted only when the user already has it installed.
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
    "linux": ("keyring set apply {name}        # if python-keyring is installed\n"
              "  or: export {name}=...        # in the shell that runs apply"),
    "other": "export {name}=...",
}


def platform_key() -> str:
    if sys.platform == "darwin":
        return "darwin"
    return "linux" if sys.platform.startswith("linux") else "other"


def how_to_store(name: str) -> str:
    """The line to tell the user when a secret is missing."""
    return INSTRUCTIONS[platform_key()].format(name=name)


def _from_keychain(name: str) -> str | None:
    """The macOS login Keychain. Absent everywhere else."""
    if sys.platform != "darwin" or not shutil.which("security"):
        return None
    result = subprocess.run(
        ["security", "find-generic-password", "-a", os.environ.get("USER", ""),
         "-s", name, "-w"],
        capture_output=True, text=True,
    )
    return (result.stdout.strip() or None) if result.returncode == 0 else None


def _from_keyring(name: str) -> str | None:
    """A Secret Service keyring, if the user has python-keyring installed."""
    if _find_spec("keyring") is None:             # never a dependency of this project
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
