from __future__ import annotations

import subprocess



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
