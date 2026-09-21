"""Telling the owner that something needs them.

Three channels, in order of how much they intrude:

  file    out/LATEST_RUN.md, always written — the morning read
  banner  a macOS notification, when something actually needs hands
  push    ntfy.sh, if a topic is configured, for when the laptop is shut

A quiet run notifies nothing. A system that pings every morning to say it found
nothing is a system that gets muted in a fortnight, and then the one morning it
matters the notification is invisible too.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def write_summary(text: str, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "LATEST_RUN.md"
    path.write_text(text)
    return path


def banner(title: str, message: str, *, sound: bool = False) -> bool:
    """A macOS notification. Returns whether it was delivered."""
    if sys.platform != "darwin" or not shutil.which("osascript"):
        return False
    safe = message.replace('"', "'").replace("\\", "")[:240]
    safe_title = title.replace('"', "'")[:60]
    script = f'display notification "{safe}" with title "{safe_title}"'
    if sound:
        script += ' sound name "Submarine"'
    result = subprocess.run(["osascript", "-e", script], capture_output=True)
    return result.returncode == 0


def push(topic: str, title: str, message: str, *, priority: str = "default") -> bool:
    """ntfy.sh, for a phone. The topic is a shared secret; anyone who knows it
    can read the notifications, so it should be long and random."""
    import httpx

    try:
        response = httpx.post(
            f"https://ntfy.sh/{topic}",
            content=message.encode("utf-8"),
            headers={"Title": title[:120], "Priority": priority, "Tags": "briefcase"},
            timeout=10.0,
        )
        return response.status_code < 300
    except Exception:                                    # noqa: BLE001
        return False


def headline(report, counts: dict) -> tuple[str, str] | None:
    """What to say, or None when the run does not warrant interrupting anyone."""
    if report.halted:
        return ("apply halted", "data/HALT exists — nothing ran.")

    urgent = counts.get("due_7", 0)
    waiting = counts.get("awaiting_review", 0)
    ready = counts.get("ready", 0)
    failures = len(report.generation_failed) + sum(1 for s in report.steps if not s.ok)

    # The bar for interrupting: something to read, something to send, something
    # closing this week, or something broken. New rows on their own do not count.
    if not (waiting or ready or urgent or failures):
        return None

    bits = []
    if ready:
        bits.append(f"{ready} ready to submit")
    if waiting:
        bits.append(f"{waiting} to review")
    if urgent:
        bits.append(f"{urgent} closing within 7 days")
    if failures:
        bits.append(f"{failures} problem{'s' if failures != 1 else ''}")

    title = "apply — needs you" if (ready or waiting) else "apply"
    return title, ", ".join(bits)


def deliver(report, counts: dict, summary: str, out_dir: Path,
            ntfy_topic: str | None = None) -> list[str]:
    """Write the summary, then interrupt only if it is worth interrupting."""
    delivered = [f"summary: {write_summary(summary, out_dir)}"]
    said = headline(report, counts)
    if said is None:
        delivered.append("quiet run: no notification sent")
        return delivered

    title, message = said
    if banner(title, message, sound=bool(counts.get("ready"))):
        delivered.append("macOS notification sent")
    if ntfy_topic and push(ntfy_topic, title, message,
                           priority="high" if counts.get("ready") else "default"):
        delivered.append(f"pushed to ntfy.sh/{ntfy_topic}")
    return delivered
