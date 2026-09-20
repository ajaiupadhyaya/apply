"""Test fixtures.

Every test runs against a temporary data directory and a temporary out/, so the
suite can never touch the owner's real apply.db, profile, or generated letters.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """An isolated data dir (with the real profile) and an isolated out/."""
    data = tmp_path / "data"
    data.mkdir()
    shutil.copy(REPO / "data" / "profile.yaml", data / "profile.yaml")
    out = tmp_path / "out"
    out.mkdir()

    monkeypatch.setenv("APPLY_DATA_DIR", str(data))
    monkeypatch.setenv("APPLY_OUT_DIR", str(out))
    return tmp_path


@pytest.fixture
def profile(workspace):
    from apply.profile import Profile

    return Profile.load()


@pytest.fixture
def conn(workspace):
    from apply import db

    db.init_db()
    connection = db.connect()
    yield connection
    connection.close()


@pytest.fixture
def blackrock_jd() -> str:
    return (FIXTURES / "blackrock.txt").read_text()


@pytest.fixture
def vcimco_jd() -> str:
    return (FIXTURES / "vcimco.txt").read_text()


def posting_from(text: str, **overrides):
    from apply.parse import parse

    parsed = parse(text)
    posting = parsed.to_posting()
    for key, value in overrides.items():
        setattr(posting, key, value)
    return posting
