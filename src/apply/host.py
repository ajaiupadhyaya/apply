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
