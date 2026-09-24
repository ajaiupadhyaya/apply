"""One order for every secret, on every platform.

`conftest` blocks `secrets.lookup` for the whole suite so no test can read the
developer's real key. This file is the one that has to exercise the real thing,
so it holds a reference taken at import time, before that patch lands. Every
test below still stubs both platform stores, so nothing here touches a Keychain.
"""

from __future__ import annotations

from apply import secrets
from apply.secrets import lookup            # the genuine function, not the block


def test_the_environment_wins(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "from-env")
    monkeypatch.setattr(secrets, "_from_keychain", lambda name: "from-keychain")
    monkeypatch.setattr(secrets, "_from_keyring", lambda name: "from-keyring")
    assert lookup("ANTHROPIC_API_KEY") == "from-env"


def test_the_keychain_is_next(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(secrets, "_from_keychain", lambda name: "from-keychain")
    monkeypatch.setattr(secrets, "_from_keyring", lambda name: "from-keyring")
    assert lookup("ANTHROPIC_API_KEY") == "from-keychain"


def test_keyring_is_the_linux_fallback(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(secrets, "_from_keychain", lambda name: None)
    monkeypatch.setattr(secrets, "_from_keyring", lambda name: "from-keyring")
    assert lookup("ANTHROPIC_API_KEY") == "from-keyring"


def test_nothing_found_is_none(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(secrets, "_from_keychain", lambda name: None)
    monkeypatch.setattr(secrets, "_from_keyring", lambda name: None)
    assert lookup("ANTHROPIC_API_KEY") is None


def test_an_empty_value_is_not_a_secret(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "   ")
    monkeypatch.setattr(secrets, "_from_keychain", lambda name: None)
    monkeypatch.setattr(secrets, "_from_keyring", lambda name: None)
    assert lookup("ANTHROPIC_API_KEY") is None


def test_a_stored_value_is_stripped(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(secrets, "_from_keychain", lambda name: "sk-test\n")
    monkeypatch.setattr(secrets, "_from_keyring", lambda name: None)
    assert lookup("ANTHROPIC_API_KEY") == "sk-test"


def test_the_keychain_is_never_asked_off_darwin(monkeypatch):
    monkeypatch.setattr(secrets.sys, "platform", "linux")
    monkeypatch.setattr(secrets.subprocess, "run", _forbidden)
    assert secrets._from_keychain("ANTHROPIC_API_KEY") is None


def test_keyring_absent_is_not_an_error(monkeypatch):
    monkeypatch.setattr(secrets, "_find_spec", lambda name: None)
    assert secrets._from_keyring("ANTHROPIC_API_KEY") is None


def test_instructions_exist_for_both_platforms():
    assert "security add-generic-password" in secrets.INSTRUCTIONS["darwin"]
    assert ("keyring" in secrets.INSTRUCTIONS["linux"]
            or "export" in secrets.INSTRUCTIONS["linux"])


def test_how_to_store_names_the_secret(monkeypatch):
    monkeypatch.setattr(secrets, "platform_key", lambda: "darwin")
    assert "APPLY_IMAP_PASSWORD" in secrets.how_to_store("APPLY_IMAP_PASSWORD")


def _forbidden(*args, **kwargs):
    raise AssertionError("a test shelled out to the platform secret store")
