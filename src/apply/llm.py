"""The Anthropic API, and nothing above it.

Every request goes through `call()`: one place that sets the model, the
fallback policy, prompt caching, structured output, the refusal check and the
usage accounting. Modules above this one decide *what* to ask; this one decides
how asking works, so that policy cannot drift between the writer and the
verifier.

The key is read through `apply.secrets` — environment, then the platform's own
store — and never written anywhere.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal, TypeVar

from pydantic import BaseModel, Field

from . import secrets

DEFAULT_MODEL = "claude-opus-5"

#: Opus 5's safety classifiers can decline a request. With this beta and
#: `fallbacks="default"`, a declined request is re-run server-side on the
#: recommended model instead of coming back as a refusal — which matters most
#: for a run nobody is watching.
FALLBACK_BETA = "server-side-fallback-2026-07-01"

#: USD per million tokens, (input, output). For telling the owner what a run
#: cost; the API is the authority on what was billed.
PRICING: dict[str, tuple[float, float]] = {
    "claude-opus-5": (5.00, 25.00),
    "claude-opus-4-8": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}

T = TypeVar("T", bound=BaseModel)


class LLMUnavailable(RuntimeError):
    """No SDK, no credential, or the request could not be completed."""


class Refused(LLMUnavailable):
    """The request was declined even after the server-side fallback."""


class Truncated(LLMUnavailable):
    """The response stopped before its structure closed, and was billed anyway.

    Carries a pessimistic `usage` — the whole output allowance — so the budget
    ledger records a cost for a call that returned nothing usable, rather than
    none at all.
    """

    def __init__(self, message: str, usage: "Usage"):
        super().__init__(message)
        self.usage = usage


# ------------------------------------------------------------------ schemas


class Package(BaseModel):
    """Everything written for one application, in a single request so the
    letter and the portal answers are drafted from the same reading of the
    posting."""

    paragraph_1: str = Field(description="The role, when you graduate, and in one clause why this firm.")
    paragraph_2: str = Field(description="One piece of work, in operational detail.")
    paragraph_3: str = Field(description="Two other pieces of work, briefly.")
    paragraph_4: str = Field(description="Why this firm, citing something specific from the posting.")
    closing: str = Field(description="Work authorization exactly as the profile states it, availability, a plain close.")
    proof_asset: str = Field(description="Which piece of work paragraph 2 is about.")
    anchor_used: str = Field(description="The exact phrase from the posting that paragraph 4 cites.")
    why_role_short: str = Field(description="Portal answer to 'Why this role / firm?', about 80 words.")
    why_role_long: str = Field(description="The same answer at about 200 words.")
    notes: str = Field(description="Anything the owner should check before sending. Empty if nothing.")

    def paragraphs(self) -> list[str]:
        # Empty ones are dropped, so a hand-edited body with three paragraphs
        # renders as three rather than with a blank fourth.
        return [p for p in (self.paragraph_1, self.paragraph_2,
                            self.paragraph_3, self.paragraph_4) if p.strip()]


class Finding(BaseModel):
    severity: Literal["blocker", "should-fix", "nit"]
    where: str = Field(description="Which paragraph, answer, or sentence.")
    problem: str
    suggestion: str


class Review(BaseModel):
    """An independent audit of a Package, by a request that did not write it."""

    verdict: Literal["send", "revise"]
    unsupported_claims: list[str] = Field(
        description="Every claim, figure, name or date in the letter or answers that "
                    "appears in neither the profile, the context documents, nor the posting.")
    authorization_correct: bool = Field(
        description="Whether any statement about work authorization or sponsorship "
                    "matches the profile exactly. True if the text makes no such statement.")
    cites_posting_specifically: bool = Field(
        description="Whether paragraph 4 names something concrete and checkable from the posting.")
    findings: list[Finding]
    strongest_sentence: str
    weakest_sentence: str

    @property
    def blockers(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == "blocker"]

    @property
    def acceptable(self) -> bool:
        """Correct, not merely good. Style findings do not block; facts do."""
        return (not self.unsupported_claims and self.authorization_correct
                and not self.blockers)


# ------------------------------------------------------------------- usage


@dataclass(slots=True)
class Usage:
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def cost(self) -> float:
        rate_in, rate_out = PRICING.get(self.model, PRICING[DEFAULT_MODEL])
        # Cache reads bill at about a tenth of input; cache writes at 1.25x.
        billed_in = (self.input_tokens + self.cache_read_tokens * 0.1
                     + self.cache_write_tokens * 1.25)
        return (billed_in * rate_in + self.output_tokens * rate_out) / 1_000_000

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            model=self.model,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
        )

    def __str__(self) -> str:
        return (f"{self.model}: {self.input_tokens:,} in "
                f"({self.cache_read_tokens:,} cached) / {self.output_tokens:,} out "
                f"≈ ${self.cost:.3f}")


def estimate(input_chars: int, *, output_tokens: int = 3500,
             model: str = DEFAULT_MODEL) -> float:
    """A pessimistic price for a call, before making it. Thinking bills as
    output, so the output allowance is generous on purpose."""
    rate_in, rate_out = PRICING.get(model, PRICING[DEFAULT_MODEL])
    return ((input_chars / 3.2) * rate_in + output_tokens * rate_out) / 1_000_000


# ---------------------------------------------------------------- plumbing

NO_CREDENTIAL = (
    "no Anthropic credential found.\n"
    "  Store it where an unattended run can find it too (this prompts, so the\n"
    "  key never enters your shell history):\n"
    f"      {secrets.how_to_store('ANTHROPIC_API_KEY')}\n"
    "  An exported ANTHROPIC_API_KEY works for a run you start yourself."
)


def _profile_dir():
    from pathlib import Path

    return Path.home() / ".config" / "anthropic"


#: Where the key lives. Read at call time, never logged, never written.
KEYCHAIN_SERVICE = "ANTHROPIC_API_KEY"


def _keychain_key(service: str = KEYCHAIN_SERVICE) -> str | None:
    """The key from the macOS login Keychain, if it is there.

    One line of `apply.secrets` kept under its old name: the test suite blocks
    the Keychain by patching this, and the platform-agnostic order now lives in
    that module.
    """
    return secrets._from_keychain(service)


def available() -> bool:
    """True when a call would have something to authenticate with."""
    if os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    return _profile_dir().exists() or secrets.lookup(KEYCHAIN_SERVICE) is not None


def _client():
    try:
        import anthropic
    except ImportError as exc:
        raise LLMUnavailable("the anthropic SDK is not installed. Run `uv sync`.") from exc
    options = {}
    if not os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        key = secrets.lookup(KEYCHAIN_SERVICE)
        if key:
            options["api_key"] = key
    try:
        client = anthropic.Anthropic(**options)
    except Exception as exc:  # noqa: BLE001 - the SDK raises several types here
        raise LLMUnavailable(f"could not construct an Anthropic client: {exc}") from exc
    # The SDK does not validate at construction, so a keyless client looks fine
    # until the first request fails. Check here, where the error can be useful.
    if not (client.api_key or getattr(client, "auth_token", None) or _profile_dir().exists()):
        raise LLMUnavailable(NO_CREDENTIAL)
    return client


def _usage(model: str, response) -> Usage:
    u = response.usage
    return Usage(
        model=model,
        input_tokens=getattr(u, "input_tokens", 0) or 0,
        output_tokens=getattr(u, "output_tokens", 0) or 0,
        cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
        cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
    )


def call(
    *,
    system: list[dict],
    user: str,
    schema: type[T],
    model: str = DEFAULT_MODEL,
    effort: str = "high",
    # Thinking bills against this too. 16,000 cut a long package off mid-JSON;
    # much past 21,000 the SDK insists on streaming for a request this size.
    max_tokens: int = 20000,
) -> tuple[T, Usage]:
    """One structured request. Raises LLMUnavailable or Refused; never returns
    a half-parsed result."""
    import anthropic
    import pydantic

    client = _client()
    try:
        response = client.beta.messages.parse(
            model=model,
            max_tokens=max_tokens,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            output_format=schema,
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.AuthenticationError as exc:
        raise LLMUnavailable("the API key was rejected. Rotate it in the Console, then "
                             f"store the new one:\n      "
                             f"{secrets.how_to_store('ANTHROPIC_API_KEY')}") from exc
    except anthropic.RateLimitError as exc:
        raise LLMUnavailable("rate limited by the API; the next run will retry.") from exc
    except anthropic.APIConnectionError as exc:
        raise LLMUnavailable("could not reach the API (network).") from exc
    except anthropic.APIStatusError as exc:
        raise LLMUnavailable(f"API error {exc.status_code}: {exc.message}") from exc
    except pydantic.ValidationError as exc:
        # The SDK parses while it builds the response, so output cut off at
        # max_tokens surfaces here as invalid JSON, before stop_reason can be read.
        chars = sum(len(b.get("text", "")) for b in system) + len(user)
        raise Truncated(
            "the response was cut off before it finished (it ran out of tokens); "
            "try again, or lower --effort.",
            Usage(model=model, input_tokens=int(chars / 3.2), output_tokens=max_tokens),
        ) from exc

    # A refusal is HTTP 200 with no usable content — check before reading it.
    if response.stop_reason == "refusal":
        category = getattr(getattr(response, "stop_details", None), "category", None)
        raise Refused(f"the request was declined{f' ({category})' if category else ''}, "
                      f"including by the server-side fallback.")
    if response.stop_reason == "max_tokens":
        raise LLMUnavailable("the response ran out of tokens before finishing.")

    parsed = response.parsed_output
    if parsed is None:
        raise LLMUnavailable("the response did not contain the expected structure.")
    return parsed, _usage(getattr(response, "model", None) or model, response)
