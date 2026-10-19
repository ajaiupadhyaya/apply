from __future__ import annotations

import pytest


def test_ping_reports_a_rejected_key(monkeypatch):
    import anthropic
    import httpx
    from apply import llm

    class Client:
        class models:
            @staticmethod
            def list(limit):
                req = httpx.Request("GET", "https://api.anthropic.com/v1/models")
                raise anthropic.AuthenticationError("bad", response=httpx.Response(401, request=req), body=None)

    monkeypatch.setattr(llm, "_client", lambda: Client())
    with pytest.raises(llm.LLMUnavailable, match="rejected"):
        llm.REAL_PING()


def test_ping_is_tripwired_in_tests():
    from apply import llm
    with pytest.raises(AssertionError, match="real Anthropic API"):
        llm.ping()


def test_imap_user_falls_back_to_email(profile):
    assert profile.imap_user == profile.email
    profile.raw["imap"] = {"user": "alerts@example.com"}
    assert profile.imap_user == "alerts@example.com"


def test_ping_reports_a_busy_api_in_a_sentence(monkeypatch):
    """A 429 or a 5xx is not a rejected key, and must not be a traceback either."""
    import anthropic
    import httpx
    from apply import llm

    class Client:
        class models:
            @staticmethod
            def list(limit):
                req = httpx.Request("GET", "https://api.anthropic.com/v1/models")
                raise anthropic.RateLimitError("slow down", response=httpx.Response(429, request=req), body=None)

    monkeypatch.setattr(llm, "_client", lambda: Client())
    with pytest.raises(llm.LLMUnavailable, match="429"):
        llm.REAL_PING()
