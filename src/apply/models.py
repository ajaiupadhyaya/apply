"""Domain types and the status state machine.

The state machine is the safety mechanism, not documentation. Two transitions
are reserved for a human hand: nothing reaches `ready` except a `review` action,
and nothing reaches `submitted` except a `submit` action. Every other caller
that tries is refused at the type level, in db.transition().
"""

from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass, field
from enum import Enum


class Track(str, Enum):
    QUANT = "quant"
    BANKING = "banking"
    ALLOCATOR = "allocator"
    CORPORATE = "corporate"

    @classmethod
    def parse(cls, value: str) -> "Track":
        try:
            return cls(value.strip().lower())
        except ValueError as exc:
            valid = ", ".join(t.value for t in cls)
            raise ValueError(f"unknown track {value!r}; expected one of: {valid}") from exc


class Status(str, Enum):
    DRAFT = "draft"
    GENERATED = "generated"
    READY = "ready"
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"
    ASSESSMENT = "assessment"
    INTERVIEWING = "interviewing"
    OFFER = "offer"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"


#: status -> statuses reachable from it.
TRANSITIONS: dict[Status, set[Status]] = {
    Status.DRAFT: {Status.GENERATED},
    # Regenerating from `generated` lands back on `generated`.
    Status.GENERATED: {Status.GENERATED, Status.READY},
    # Regenerating from `ready` drops back to `generated` and clears reviewed_at.
    Status.READY: {Status.GENERATED, Status.SUBMITTED},
    Status.SUBMITTED: {
        Status.ACKNOWLEDGED,
        Status.ASSESSMENT,
        Status.INTERVIEWING,
        Status.OFFER,
        Status.REJECTED,
    },
    Status.ACKNOWLEDGED: {
        Status.ASSESSMENT,
        Status.INTERVIEWING,
        Status.OFFER,
        Status.REJECTED,
    },
    Status.ASSESSMENT: {Status.INTERVIEWING, Status.OFFER, Status.REJECTED},
    Status.INTERVIEWING: {Status.OFFER, Status.REJECTED},
    Status.OFFER: {Status.REJECTED},
    Status.REJECTED: set(),
    Status.WITHDRAWN: set(),
}

#: Reachable from anywhere except the terminal states.
TERMINAL = {Status.REJECTED, Status.WITHDRAWN}

#: Statuses a machine may never write on its own. The value is the name of the
#: one CLI/dashboard action permitted to perform the transition.
HUMAN_GATED: dict[Status, str] = {
    Status.READY: "review",
    Status.SUBMITTED: "submit",
}


class TransitionError(RuntimeError):
    """A refused status change. The message is written for the owner, not a log."""


def check_transition(current: Status, target: Status, via: str) -> None:
    """Raise TransitionError unless `current -> target` is legal under action `via`."""
    if target is Status.WITHDRAWN:
        if current in TERMINAL:
            raise TransitionError(f"already {current.value}; nothing to withdraw")
        return

    allowed = TRANSITIONS.get(current, set())
    if target not in allowed:
        if target is Status.SUBMITTED and current is Status.GENERATED:
            raise TransitionError(
                "this application has not been read yet. Run `apply review <slug>` "
                "first — generated documents cannot go straight to submitted."
            )
        pretty = ", ".join(sorted(s.value for s in allowed)) or "nothing"
        raise TransitionError(
            f"cannot go from {current.value} to {target.value}; "
            f"from {current.value} you can only reach: {pretty}"
        )

    required = HUMAN_GATED.get(target)
    if required is not None and via != required:
        raise TransitionError(
            f"{target.value} is a human-only state; it can only be set by the "
            f"`{required}` action, not by `{via}`"
        )


class EventKind(str, Enum):
    CREATED = "created"
    GENERATED = "generated"
    REVIEWED = "reviewed"
    SUBMITTED = "submitted"
    ACK = "ack"
    OA_RECEIVED = "oa_received"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECT = "reject"
    WITHDRAWN = "withdrawn"
    NOTE = "note"


@dataclass(slots=True)
class Posting:
    slug: str
    company: str
    role: str
    track: str
    jd_raw: str
    id: int | None = None
    source: str | None = None
    source_url: str | None = None
    location: str | None = None
    comp: str | None = None
    deadline: _dt.date | None = None
    posted_at: _dt.date | None = None
    priority: int = 3
    created_at: str | None = None
    # Set by a discovery pass; None for a posting added by hand.
    fingerprint: str | None = None
    score: int | None = None
    score_verdict: str | None = None
    score_reasons: str | None = None
    discovered_at: str | None = None


@dataclass(slots=True)
class Application:
    posting_id: int
    id: int | None = None
    status: str = Status.DRAFT.value
    resume_variant: str | None = None
    letter_path: str | None = None
    resume_path: str | None = None
    fieldpack_path: str | None = None
    reviewed_at: str | None = None
    submitted_at: str | None = None
    notes: str | None = None


@dataclass(slots=True)
class Event:
    application_id: int
    kind: str
    id: int | None = None
    occurred_at: str | None = None
    detail: str | None = None


@dataclass(slots=True)
class Followup:
    application_id: int
    due_on: _dt.date
    action: str
    id: int | None = None
    done: bool = False


@dataclass(slots=True)
class Row:
    """A posting joined to its application, as the dashboard and `status` see it."""

    posting: Posting
    application: Application
    followups: list[Followup] = field(default_factory=list)

    @property
    def days_left(self) -> int | None:
        if self.posting.deadline is None:
            return None
        return (self.posting.deadline - _dt.date.today()).days


_SLUG_STRIP = re.compile(r"[^a-z0-9]+")


def slugify(company: str, role: str, year: int | str | None = None) -> str:
    """<company>-<role>-<year>, lowercase, hyphenated. Role is trimmed to keep it readable."""
    parts = [_SLUG_STRIP.sub("-", company.lower()).strip("-")]
    # Drop filler that makes every slug look alike. Filtering the ORIGINAL words
    # rather than the slugified ones matters: "M&A" slugifies to "m-a", and
    # filtering after the split would delete the "a" as an article.
    filler = {"the", "a", "an", "of", "for", "and", "program", "position", "job", "role"}
    words = [
        slugged
        for word in role.lower().split()
        if word.strip(".,()") not in filler
        and (slugged := _SLUG_STRIP.sub("-", word).strip("-"))
    ]
    # Don't say the year twice: "quillon-2027-analyst-2027" reads like a bug.
    year_s = str(year) if year else None
    if year_s:
        words = [w for w in words if w != year_s]
    parts.append("-".join(words[:5]))
    if year_s:
        parts.append(year_s)
    return "-".join(p for p in parts if p)
