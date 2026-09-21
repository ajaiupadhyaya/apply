"""Every host this system is allowed to send a request to, and why.

The constraint that matters is not "makes no network calls" — discovery is
nothing but network calls. It is that **nothing here ever transmits to an
employer**. A job board's public search API is a read dressed as a POST; an
application portal is not, and no code path reaches one.

This module exists so that rule is checkable rather than merely intended.
tests/test_acceptance.py asserts that every outbound call site in src/ belongs
to a module listed here, so adding one somewhere new fails the suite until it
is declared and justified.
"""

from __future__ import annotations

#: module -> (hosts it may reach, why that is not an employer)
ALLOWED: dict[str, tuple[tuple[str, ...], str]] = {
    "apply.sources.ats": (
        ("boards-api.greenhouse.io", "api.lever.co", "api.ashbyhq.com",
         "*.myworkdayjobs.com"),
        "Public job-board APIs. Workday's /wday/cxs/ endpoint takes a POST "
        "because it is a search query, not a submission — it is the same call "
        "the employer's own careers page makes to render itself.",
    ),
    "apply.resolve": (
        ("*",),
        "Fetches one careers page, by GET, to identify which board a firm uses. "
        "Reads the HTML and nothing else.",
    ),
    "apply.notify": (
        ("ntfy.sh",),
        "Push notification to the owner's own phone. Carries a count, never a "
        "posting and never anything about the owner.",
    ),
    "apply.llm": (
        ("api.anthropic.com",),
        "Letter drafting and review, via the SDK.",
    ),
    "apply.discover": (
        ("imap.gmail.com",),
        "Reads the owner's own alert mail, read-only, over IMAP.",
    ),
    "apply.context": (
        ("api.github.com",),
        "Reads the owner's own public READMEs through their gh session, by GET, "
        "to use as source material.",
    ),
    "apply.cli": (
        ("*",),
        "`apply add --url` fetches one careers page the owner named. Refuses "
        "Handshake hosts outright.",
    ),
}

#: Machinery that would make submitting possible. None of it may appear.
FORBIDDEN_MACHINERY = (
    "selenium", "playwright", "webdriver", "puppeteer", "pyppeteer",
    "mechanize", "robobrowser", "form.submit", "submit_form",
)


def why(module: str) -> str:
    entry = ALLOWED.get(module)
    return entry[1] if entry else "not declared — this module may not make requests"
