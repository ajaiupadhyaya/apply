"""The starter repo a friend clones: every tracked file, none of the owner's life."""

from __future__ import annotations

import re
import runpy
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
export = runpy.run_path(str(REPO / "scripts" / "export_starter.py"))

NEVER_TRACKED = ("data/profile.yaml", "data/profile.private.yaml", "data/search.yaml",
                 "data/employers.yaml", "tests/fixtures/score_corpus.local.json")


def test_the_export_deny_list_covers_the_tests_one():
    text = (REPO / "tests" / "test_setup.py").read_text(encoding="utf-8")
    block = re.search(r"AUTHORS_BIOGRAPHY = \((.*?)\)", text, re.S).group(1)
    assert set(re.findall(r'"([^"]+)"', block)) <= set(export["BIOGRAPHY"])


def test_private_files_are_not_tracked():
    tracked = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True,
                             text=True, encoding="utf-8", check=True).stdout.split("\0")
    assert not set(NEVER_TRACKED) & set(tracked)
    assert not any(p.startswith((".superpowers/", ".claude/")) for p in tracked)


def test_export_builds_a_clean_single_commit_repo(tmp_path):
    target = tmp_path / "apply-starter"
    copied = export["export"](target, REPO)
    assert "src/apply/cli.py" in copied
    assert not any(p.startswith(("docs/superpowers/", ".reviews/")) for p in copied)
    assert not (target / "data" / "profile.yaml").exists()
    assert (target / "data" / "profile.example.yaml").exists()
    log = subprocess.run(["git", "log", "--oneline"], cwd=target, capture_output=True,
                         text=True, encoding="utf-8", check=True)
    assert len(log.stdout.strip().splitlines()) == 1
    files = [p for p in target.rglob("*") if p.is_file() and ".git" not in p.parts]
    assert export["biography_in"](files) == []
    for owner_only in export["EXCLUDE_FILES"]:
        assert owner_only not in copied
        assert not (target / owner_only).exists()
    assert export["EXCLUDE_FILES"] == ("scripts/export_starter.py", "tests/test_export.py")


def _hit(tmp_path, text):
    f = tmp_path / "f.txt"
    f.write_text(text, encoding="utf-8")
    return export["biography_in"]([f])


def test_compound_identifiers_and_loose_attribution_are_flagged(tmp_path):
    for text in ("mail ajaiupad@gmail.com", "user ajaiupadhyaya home", "ajaiupadhyayaak",
                 "/Users/ajaiupadhyaya/x", "ohcamel_x", "github.com/ajaiupadhyaya/other",
                 "Copyright (c) 2026 Ajai Upadhyaya, VCU",
                 "@namespace https://github.com/ajaiupadhyaya ajaiupad@x.com"):
        assert _hit(tmp_path, text), text


def test_only_the_exact_attribution_strings_pass(tmp_path):
    for text in export["ALLOWED_STRINGS"]:
        assert _hit(tmp_path, text) == [], text


def test_the_ats_vocabulary_entries_pass_but_the_words_alone_do_not(tmp_path):
    assert _hit(tmp_path, '    "Bloomberg": r"bloomberg",') == []
    for text in ("interned at Bloomberg", "Morningstar analyst", "WRDS access via school"):
        assert _hit(tmp_path, text), text


def test_export_refuses_a_tracked_biography(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.txt").write_text("I studied at VCU\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True)
    with pytest.raises(SystemExit):
        export["export"](tmp_path / "out", repo)
