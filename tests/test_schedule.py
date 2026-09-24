"""The morning run, on both platforms. No file outside tmp_path is touched.

Nothing here calls launchctl, systemctl or crontab: every one of them goes
through `schedule._run`, which the tests intercept. Installing a timer is
persistent configuration on someone's machine, and a test suite is not a person.
"""

from __future__ import annotations

import plistlib
import types

import pytest

from apply import notify as notify_mod
from apply import schedule as schedule_mod


@pytest.fixture
def plan(tmp_path):
    return schedule_mod.Schedule(hour=6, minute=30, project=tmp_path)


def test_launchd_renders_a_plist(plan):
    text = schedule_mod.backend("darwin").render(plan)
    assert "<key>StartCalendarInterval</key>" in text
    assert "apply run --notify" in text


def test_the_agent_is_not_named_after_a_person(plan):
    """A public repo installs agents on strangers' machines. The label is theirs."""
    assert schedule_mod.LABEL == "apply.daily"
    assert schedule_mod.LaunchdBackend().as_plist(plan)["Label"] == schedule_mod.LABEL
    assert schedule_mod.LaunchdBackend().plist_path().name == "apply.daily.plist"


def test_an_agent_under_the_old_label_is_retired_not_orphaned(tmp_path, monkeypatch):
    """Renaming the label would otherwise leave the old agent loaded forever."""
    agents = tmp_path / "LaunchAgents"
    agents.mkdir()
    monkeypatch.setattr(schedule_mod.LaunchdBackend, "agents_dir", lambda self: agents)
    argv_seen = []
    monkeypatch.setattr(schedule_mod, "_run",
                        lambda argv, *rest: (argv_seen.append(argv), _exited(0))[1])

    legacy = agents / f"{schedule_mod.LEGACY_LABELS[0]}.plist"
    legacy.write_bytes(plistlib.dumps({"Label": schedule_mod.LEGACY_LABELS[0]}))

    # It is found, so `apply schedule` does not report an empty morning while a
    # job is still running, and `--remove` takes it away.
    assert schedule_mod.LaunchdBackend().status()["installed"] is True
    assert schedule_mod.LaunchdBackend().remove() is True
    assert not legacy.exists()
    assert ["launchctl", "unload", str(legacy)] in argv_seen


def test_installing_retires_the_old_agent_before_loading_the_new_one(tmp_path, monkeypatch):
    agents = tmp_path / "LaunchAgents"
    agents.mkdir()
    monkeypatch.setattr(schedule_mod.LaunchdBackend, "agents_dir", lambda self: agents)
    monkeypatch.setattr(schedule_mod.sys, "platform", "darwin")
    monkeypatch.setattr(schedule_mod, "_run", lambda argv, *rest: _exited(0))
    legacy = agents / f"{schedule_mod.LEGACY_LABELS[0]}.plist"
    legacy.write_bytes(plistlib.dumps({"Label": schedule_mod.LEGACY_LABELS[0]}))

    path = schedule_mod.LaunchdBackend().install(schedule_mod.Schedule(project=tmp_path))

    assert path.name == f"{schedule_mod.LABEL}.plist"
    assert not legacy.exists()
    assert [p.name for p in sorted(agents.iterdir())] == [f"{schedule_mod.LABEL}.plist"]


def test_systemd_renders_a_timer_and_a_service(plan):
    # SystemdBackend directly, not backend("linux"): which systemd unit a Linux
    # box gets depends on whether systemctl is on PATH, and this test also runs
    # on macOS, where it is not.
    rendered = schedule_mod.SystemdBackend().render(plan)
    assert "OnCalendar=*-*-* 06:30:00" in rendered
    assert "Type=oneshot" in rendered
    assert str(plan.project) in rendered
    assert "apply run --notify" in rendered


def test_cron_renders_one_line(plan):
    line = schedule_mod.CronBackend().render(plan)
    assert line.startswith("30 6 * * *")
    assert "apply run --notify" in line
    assert schedule_mod.CronBackend.MARKER in line
    assert "\n" not in line


def test_installing_a_timer_writes_only_under_the_unit_dir(tmp_path, monkeypatch):
    units = tmp_path / "units"
    monkeypatch.setattr(schedule_mod.SystemdBackend, "unit_dir", lambda self: units)
    calls = []
    monkeypatch.setattr(schedule_mod, "_run", lambda *args: calls.append(args))

    schedule_mod.SystemdBackend().install(schedule_mod.Schedule(project=tmp_path))

    assert (units / "apply.service").exists() and (units / "apply.timer").exists()
    assert any("--user" in " ".join(call[0]) for call in calls)
    assert any("daemon-reload" in " ".join(call[0]) for call in calls)


def test_removing_a_timer_takes_both_units_away(tmp_path, monkeypatch):
    units = tmp_path / "units"
    monkeypatch.setattr(schedule_mod.SystemdBackend, "unit_dir", lambda self: units)
    monkeypatch.setattr(schedule_mod, "_run", lambda *args: None)

    assert schedule_mod.SystemdBackend().remove() is False     # nothing installed

    schedule_mod.SystemdBackend().install(schedule_mod.Schedule(project=tmp_path))
    assert schedule_mod.SystemdBackend().remove() is True
    assert not any(units.iterdir())


def test_a_timer_status_reads_the_unit_it_wrote(tmp_path, monkeypatch):
    units = tmp_path / "units"
    monkeypatch.setattr(schedule_mod.SystemdBackend, "unit_dir", lambda self: units)
    monkeypatch.setattr(schedule_mod, "_run", lambda *args: _exited(0))

    assert schedule_mod.SystemdBackend().status() == {"installed": False}

    schedule_mod.SystemdBackend().install(
        schedule_mod.Schedule(hour=7, minute=5, project=tmp_path))
    state = schedule_mod.SystemdBackend().status()

    assert state["installed"] is True and state["at"] == "07:05"
    assert state["loaded"] is True
    assert "apply run --notify" in state["command"]


def test_installing_a_cron_line_keeps_the_others(tmp_path, monkeypatch):
    existing = "0 9 * * * backup\n"
    written = {}
    monkeypatch.setattr(schedule_mod.CronBackend, "_read", lambda self: existing)
    monkeypatch.setattr(schedule_mod.CronBackend, "_write",
                        lambda self, text: written.setdefault("text", text))

    schedule_mod.CronBackend().install(schedule_mod.Schedule(project=tmp_path))

    lines = written["text"].splitlines()
    assert lines[0] == "0 9 * * * backup"
    assert sum(1 for line in lines if schedule_mod.CronBackend.MARKER in line) == 1


def test_installing_twice_replaces_the_line(tmp_path, monkeypatch):
    plan = schedule_mod.Schedule(project=tmp_path)
    existing = "0 9 * * * backup\n" + schedule_mod.CronBackend().render(plan) + "\n"
    written = {}
    monkeypatch.setattr(schedule_mod.CronBackend, "_read", lambda self: existing)
    monkeypatch.setattr(schedule_mod.CronBackend, "_write",
                        lambda self, text: written.setdefault("text", text))

    schedule_mod.CronBackend().install(schedule_mod.Schedule(hour=7, minute=5,
                                                             project=tmp_path))

    lines = [line for line in written["text"].splitlines()
             if schedule_mod.CronBackend.MARKER in line]
    assert len(lines) == 1 and lines[0].startswith("5 7 * * *")


def test_removing_a_cron_line_keeps_the_others(monkeypatch):
    existing = "0 9 * * * backup\n30 6 * * * cd /x && uv run apply run --notify  # apply\n"
    written = {}
    monkeypatch.setattr(schedule_mod.CronBackend, "_read", lambda self: existing)
    monkeypatch.setattr(schedule_mod.CronBackend, "_write",
                        lambda self, text: written.setdefault("text", text))

    assert schedule_mod.CronBackend().remove() is True
    assert "backup" in written["text"] and "apply run" not in written["text"]


def test_removing_nothing_says_so(monkeypatch):
    monkeypatch.setattr(schedule_mod.CronBackend, "_read", lambda self: "0 9 * * * backup\n")
    monkeypatch.setattr(schedule_mod.CronBackend, "_write",
                        lambda self, text: pytest.fail("rewrote a crontab it did not own"))

    assert schedule_mod.CronBackend().remove() is False


def test_a_cron_status_reads_its_own_line(tmp_path, monkeypatch):
    plan = schedule_mod.Schedule(hour=7, minute=5, project=tmp_path)
    monkeypatch.setattr(schedule_mod.CronBackend, "_read",
                        lambda self: "0 9 * * * backup\n" + schedule_mod.CronBackend().render(plan))

    state = schedule_mod.CronBackend().status()

    assert state["installed"] is True and state["at"] == "07:05"
    assert "apply run --notify" in state["command"]


def test_the_backend_follows_the_platform(monkeypatch):
    assert isinstance(schedule_mod.backend("darwin"), schedule_mod.LaunchdBackend)
    monkeypatch.setattr(schedule_mod.shutil, "which", lambda name: "/usr/bin/systemctl")
    assert isinstance(schedule_mod.backend("linux"), schedule_mod.SystemdBackend)
    monkeypatch.setattr(schedule_mod.shutil, "which", lambda name: None)
    assert isinstance(schedule_mod.backend("linux"), schedule_mod.CronBackend)


def test_an_unknown_platform_says_what_to_do_instead():
    with pytest.raises(RuntimeError, match="own cron"):
        schedule_mod.backend("sunos5")


def test_the_module_level_calls_delegate(monkeypatch):
    monkeypatch.setattr(schedule_mod, "backend", lambda: _Spy())
    assert schedule_mod.status() == {"installed": "spied"}
    assert schedule_mod.remove() is True


def test_the_banner_reaches_a_linux_desktop(monkeypatch):
    seen = {}

    def record(argv, **kwargs):
        seen["argv"] = argv
        return _exited(0)

    monkeypatch.setattr(notify_mod.sys, "platform", "linux")
    monkeypatch.setattr(notify_mod.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(notify_mod.subprocess, "run", record)

    assert notify_mod.banner("apply — needs you", "2 to review") is True
    assert seen["argv"][0] == "notify-send"
    assert "2 to review" in seen["argv"]


def test_the_banner_is_silent_where_it_has_no_desktop(monkeypatch):
    monkeypatch.setattr(notify_mod.sys, "platform", "linux")
    monkeypatch.setattr(notify_mod.shutil, "which", lambda name: None)
    monkeypatch.setattr(notify_mod.subprocess, "run", _forbidden)

    assert notify_mod.banner("apply", "anything") is False


def _exited(code: int):
    return types.SimpleNamespace(returncode=code, stdout="", stderr="")


def _forbidden(*args, **kwargs):
    raise AssertionError("a test shelled out to the desktop")


class _Spy:
    def status(self):
        return {"installed": "spied"}

    def remove(self):
        return True
