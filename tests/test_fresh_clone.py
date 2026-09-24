"""What a stranger gets: every command, on a data directory that starts empty.

This is the quick start as a test. It drives the real CLI through Typer's runner
against a temporary data directory and a temporary out/, so it can never reach
the author's own files — and it fails if any command starts writing outside
them. Nothing here calls a model: `gen` is the one command this file leaves out,
because it is the one that costs money.
"""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest
from typer.testing import CliRunner

from apply.cli import app
from apply.generate import repo_root

#: Every file a user of this repository writes for themselves. None of them may
#: be committable: a cloner who runs `git add -A` must not be able to push their
#: own search, their own profile, or their own database back to the project.
USER_WRITES = [
    "data/profile.yaml",
    "data/profile.private.yaml",
    "data/employers.yaml",
    "data/search.yaml",
    "data/alerts.json",
    "data/apply.db",
    "data/HALT",
    "data/context/notes.md",
    "out/some-firm-role-2027/letter.pdf",
]


@pytest.fixture
def fresh(isolated_data_dir):
    """A CLI runner over the empty data/ and out/ that `isolated_data_dir` makes.

    It used to set `APPLY_DATA_DIR` itself. That is now the autouse fixture's
    job for the whole suite, so this only names it — which is also what says
    the empty directory these tests need is the one every other test gets.
    """
    return CliRunner()


def run(runner, *args):
    result = runner.invoke(app, list(args))
    assert result.exit_code == 0, f"{args} exited {result.exit_code}\n{result.output}"
    return result.output


def fails(runner, *args):
    """A command that is meant to refuse: exit non-zero, and say why."""
    result = runner.invoke(app, list(args))
    assert result.exit_code != 0, f"{args} was expected to fail\n{result.output}"
    return result.output


def test_the_quick_start_works_on_an_empty_directory(fresh):
    run(fresh, "setup", "--non-interactive")
    run(fresh, "seed")
    assert "draft" in run(fresh, "status")
    run(fresh, "digest")
    run(fresh, "targets")
    run(fresh, "search")
    run(fresh, "rescore", "--dry-run")
    run(fresh, "spend")
    run(fresh, "runs")
    run(fresh, "doctor")


def test_the_quick_start_stays_inside_its_own_directories(fresh, tmp_path):
    before = sorted(p.name for p in (repo_root() / "data").iterdir())

    run(fresh, "setup", "--non-interactive")
    run(fresh, "seed")
    run(fresh, "followup", "ashcombe-investment-intern-2027", "call someone", "--in", "3")

    assert sorted(p.name for p in (repo_root() / "data").iterdir()) == before
    assert (tmp_path / "data" / "apply.db").exists()


def test_a_new_database_has_no_table_nothing_writes_to(fresh, tmp_path):
    """A `contact` table sat in the schema for a feature that was never built."""
    import sqlite3

    run(fresh, "setup", "--non-interactive")
    with sqlite3.connect(tmp_path / "data" / "apply.db") as conn:
        tables = {name for (name,) in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
    # `run` and `spend` are created by the modules that own them, on first use.
    assert tables == {"posting", "application", "event", "followup"}


def test_the_commands_that_need_a_profile_say_how_to_get_one(fresh):
    """Before `apply setup` there is no profile, and the advice must be current."""
    output = fails(fresh, "doctor")
    assert "apply setup" in output


def test_setup_refuses_to_flatten_a_profile_that_exists(fresh):
    run(fresh, "setup", "--non-interactive")
    assert "--force" in fails(fresh, "setup", "--non-interactive")


def test_every_command_in_help_is_documented_in_the_readme(fresh):
    listed = _commands(run(fresh, "--help"))
    readme = (repo_root() / "README.md").read_text()
    missing = sorted(name for name in listed if f"apply {name}" not in readme)
    assert missing == [], f"commands with no line in the README: {missing}"


def test_every_file_a_user_writes_is_gitignored():
    """A stranger's own data must not be committable back to a public repo."""
    if shutil.which("git") is None:                    # pragma: no cover
        pytest.skip("git is not installed")
    result = subprocess.run(
        ["git", "-C", str(repo_root()), "check-ignore", *USER_WRITES],
        capture_output=True, text=True,
    )
    ignored = set(result.stdout.split())
    assert sorted(set(USER_WRITES) - ignored) == []


def test_the_example_files_are_still_committable():
    """The other half of the rule: what ships with the repo must not be ignored."""
    if shutil.which("git") is None:                    # pragma: no cover
        pytest.skip("git is not installed")
    shipped = ["data/profile.example.yaml", "data/employers.example.yaml",
               "data/profile.private.example.yaml"]
    result = subprocess.run(
        ["git", "-C", str(repo_root()), "check-ignore", *shipped],
        capture_output=True, text=True,
    )
    assert result.stdout.strip() == ""


def test_the_wrong_file_is_refused_in_a_sentence(fresh, tmp_path):
    """`--file` wants an alert export; a JSONDecodeError explains nothing."""
    run(fresh, "setup", "--non-interactive")
    not_an_export = tmp_path / "posting.txt"
    not_an_export.write_text("Some Firm — Analyst\nLocation: New York\n")

    output = fails(fresh, "ingest", "--file", str(not_an_export))

    assert "not an alert export" in output
    assert "Traceback" not in output


def test_the_scheduler_help_names_more_than_one_platform(fresh):
    """`schedule` grew systemd and cron backends; its help said launchd only."""
    output = run(fresh, "schedule", "--help").lower()
    assert "systemd" in output and "launchd" in output
    assert "launchagent" not in output


def test_an_unsupported_platform_gets_a_sentence_not_a_traceback(fresh, monkeypatch):
    from apply import schedule as schedule_mod

    def unsupported(platform=None):
        raise RuntimeError("no scheduler for this platform; run `apply run` from your own cron")

    monkeypatch.setattr(schedule_mod, "backend", unsupported)
    for flags in (["--show"], ["--remove"], []):
        output = fails(fresh, "schedule", *flags)
        assert "your own cron" in output


def test_the_dashboard_answers_on_a_fresh_profile(fresh):
    from fastapi.testclient import TestClient

    run(fresh, "setup", "--non-interactive")
    run(fresh, "seed")
    from apply.web.app import app as web

    response = TestClient(web).get("/")
    assert response.status_code == 200
    assert "Ashcombe Trust" in response.text


def _commands(help_text: str) -> set[str]:
    """The command names out of `--help`, whether or not rich drew a box.

    A command name starts its row; a wrapped description line is indented under
    the description column, so the leading-space count tells them apart.
    """
    plain = re.sub(r"\x1b\[[0-9;]*m", "", help_text)      # CI colours it; a laptop does not
    names = {match.group(1)
             for match in (re.match(r"^[│|]?\s{1,3}([a-z][a-z0-9-]*)\s{2,}\S", line)
                           for line in plain.splitlines())
             if match}
    assert len(names) > 20, f"parsed only {sorted(names)} out of --help"
    return names


# ----------------------------------------------- the first hour, question by
# question. Everything below was found by a reader following the quick start
# literally: pressing Enter at a prompt, running the command the README leads
# with, and looking for the slug every other command wants.


def test_a_blank_graduation_month_is_refused_at_the_prompt(fresh):
    """Answering nothing used to write ASK and kill the next command."""
    result = fresh.invoke(app, ["setup"], input="\n" * 40)

    assert result.exit_code != 0
    assert "2027-05" in result.output                  # the shape it wants
    assert "Traceback" not in result.output


def test_a_profile_that_cannot_be_read_gets_a_sentence_not_a_traceback(fresh, tmp_path):
    run(fresh, "setup", "--non-interactive")
    run(fresh, "seed")
    profile = tmp_path / "data" / "profile.yaml"
    profile.write_text(profile.read_text().replace("grad_expected: 2027-06",
                                                   "grad_expected: ASK"))

    # The commands that derive class standing and the eligibility window from
    # it. The value is read lazily, so before this each of them reached the
    # gate and died there in a rich traceback.
    for command in (["discover", "--dry-run"], ["rescore", "--dry-run"]):
        output = fails(fresh, *command)
        assert "Traceback" not in output, command
        assert "grad_expected" in output and "2027-05" in output, command

    # …and two that do not. `apply search` reads the profile's `search:` block
    # and `apply status` reads the database; neither asks for a date, so both
    # still work. "Fail with a sentence" is not licence to refuse a command
    # that has no reason to care.
    assert "thresholds" in run(fresh, "search")
    assert "ashcombe-investment-intern-2027" in run(fresh, "status")


def test_doctor_says_which_holes_are_load_bearing(fresh, tmp_path):
    run(fresh, "setup", "--non-interactive")
    profile = tmp_path / "data" / "profile.yaml"
    profile.write_text(profile.read_text().replace("grad_expected: 2027-06",
                                                   "grad_expected: ASK"))

    output = run(fresh, "doctor")

    blocking, rest = output.split("nothing is waiting on it")
    assert "education[0].grad_expected" in blocking
    assert "identity.phone" in rest          # a private value nothing is waiting on
    assert "identity.phone" not in blocking


def test_setup_writes_a_search_for_the_city_it_asked_about(fresh, tmp_path):
    """The wizard asks where you want to work; the gate has to hear the answer."""
    run(fresh, "setup", "--non-interactive")            # the persona lives in London

    written = (tmp_path / "data" / "search.yaml").read_text()
    assert "London" in written
    assert "London +25" in run(fresh, "search")
    # …and the shipped placeholder geography is gone, rather than sitting
    # underneath the answer scoring somewhere the user never named.
    assert "your home city" not in run(fresh, "search")


def test_search_prints_the_thresholds_the_gate_will_use(fresh, tmp_path):
    """profile.private.example.yaml sets them, and setup copies it onto your disk."""
    run(fresh, "setup", "--non-interactive")
    private = tmp_path / "data" / "profile.private.yaml"
    private.write_text(private.read_text().replace("pursue: 70", "pursue: 40")
                       .replace("maybe: 45", "maybe: 20"))

    output = run(fresh, "search")

    assert "pursue ≥ 40" in output and "maybe ≥ 20" in output
    assert "profile.private.yaml" in output              # and where it came from


def test_status_prints_the_slug_every_other_command_wants(fresh):
    run(fresh, "setup", "--non-interactive")
    run(fresh, "seed")

    assert "ashcombe-investment-intern-2027" in run(fresh, "status")
    assert "ashcombe-investment-intern-2027" in run(fresh, "digest")


def test_the_persona_profile_keeps_the_line_saying_it_is_fiction(fresh, tmp_path):
    run(fresh, "setup", "--persona")

    first_line = (tmp_path / "data" / "profile.yaml").read_text().splitlines()[0]
    assert "does not exist" in first_line


def test_the_numbers_tool_runs_before_anything_has_been_run(fresh, tmp_path):
    """The command the README leads with, on the database `apply setup` writes."""
    import importlib.util

    run(fresh, "setup", "--non-interactive")
    spec = importlib.util.spec_from_file_location(
        "apply_numbers", repo_root() / "tools" / "numbers.py")
    numbers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(numbers)

    printed = []
    numbers.print = printed.append                       # noqa: A001
    numbers.main()

    output = "\n".join(printed)
    assert "vocabulary" in output                        # what it could compute
    assert "no `run` table yet" in output                # and what it could not
    assert "apply run" in output                         # and whose job that is


# ------------------------------------------------------- paste, on any laptop


def test_the_clipboard_is_read_by_whichever_tool_is_installed(fresh, monkeypatch):
    """--clipboard was pbpaste or nothing, so on Linux it was nothing."""
    import subprocess as sp

    from apply import cli

    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/xclip"
                        if name == "xclip" else None)
    calls = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return sp.CompletedProcess(command, 0, stdout="Some Firm\nAnalyst\n", stderr="")

    monkeypatch.setattr(cli.subprocess, "run", fake_run)

    assert cli.read_clipboard() == "Some Firm\nAnalyst\n"
    assert calls == [["xclip", "-selection", "clipboard", "-o"]]


def test_a_machine_with_no_clipboard_is_told_about_stdin(fresh, monkeypatch):
    from apply import cli

    run(fresh, "setup", "--non-interactive")
    monkeypatch.setattr(cli.shutil, "which", lambda name: None)

    output = fails(fresh, "add", "--clipboard")

    assert "--stdin" in output
    assert "pbpaste" in output and "xclip" in output      # what it looked for


def test_a_clipboard_tool_that_fails_says_which_one(fresh, monkeypatch):
    import subprocess as sp

    from apply import cli

    run(fresh, "setup", "--non-interactive")
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/wl-paste"
                        if name == "wl-paste" else None)
    monkeypatch.setattr(cli.subprocess, "run", lambda command, **kw: sp.CompletedProcess(
        command, 1, stdout="", stderr="cannot connect to the compositor"))

    output = fails(fresh, "add", "--clipboard")

    assert "wl-paste" in output and "compositor" in output
    assert "--stdin" in output
