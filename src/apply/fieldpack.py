"""The autofill layer: a posting plus the profile become a list of portal fields.

This is the least glamorous file in the repo and it saves the most time. The
dashboard renders it as a column of copy buttons in roughly the order Workday and
Greenhouse ask for things, so filling a portal is a column of clicks instead of a
column of retyping.

Nothing sensitive goes in here. SSN, date of birth, government ID, and bank
details are not in the profile, so they cannot reach a fieldpack; the owner types
those at submit time or not at all.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from .models import Posting
from .profile import Profile


def _field(labels: list[str], value, *, note: str | None = None) -> dict | None:
    if value in (None, "", []):
        return None
    out = {"labels": labels, "value": str(value)}
    if note:
        out["note"] = note
    return out


def build(profile: Profile, posting: Posting, answers: dict | None = None) -> dict:
    ident = profile.identity
    loc = ident.get("location", {}) or {}
    auth = profile.authorization
    edu = profile.current_education

    sponsorship = "Yes" if profile.needs_sponsorship_ever else "No"

    raw = [
        # Identity, in the order portals ask.
        _field(["First Name", "Legal First Name", "Given Name"], ident.get("legal_first")),
        _field(["Last Name", "Legal Last Name", "Family Name", "Surname"], ident.get("legal_last")),
        _field(["Preferred Name", "Nickname", "Goes By"], ident.get("preferred_name")),
        _field(["Email", "Email Address"], profile.email),
        _field(["Phone", "Phone Number", "Mobile", "Cell"], profile.phone,
               note="from profile.private.yaml" if profile.phone else None),
        _field(["Address", "Street Address", "Address Line 1"],
               ident.get("street_address")),
        _field(["City"], loc.get("city")),
        _field(["State", "State/Province", "Province"], loc.get("state")),
        _field(["Country"], loc.get("country")),

        # Education.
        _field(["School", "University", "Institution", "College"], profile.school),
        _field(["Degree", "Degree Type"], edu.get("degree")),
        _field(["Major", "Field of Study", "Concentration"], edu.get("major")),
        _field(["Expected Graduation", "Graduation Date", "Anticipated Completion",
                "Expected Graduation Date"], profile.grad_month_year),
        _field(["GPA", "Cumulative GPA", "Grade Point Average"], profile.gpa,
               note="from profile.private.yaml" if profile.gpa else None),

        # Work authorization — the two questions every portal asks, and the one
        # place a wrong answer is disqualifying.
        _field(["Are you legally authorized to work in the United States?",
                "Work Authorization", "Are you authorized to work in the US?"],
               "Yes" if profile.work_authorized else "No"),
        _field(["Will you now or in the future require sponsorship?",
                "Do you require sponsorship for employment visa status?",
                "Will you require sponsorship?"], sponsorship),
        _field(["Have you been convicted of a felony?"],
               "Yes" if auth.get("felony") else "No"),
        _field(["Are you a veteran?", "Veteran Status"],
               "Yes" if auth.get("veteran") else "No"),

        # Links.
        _field(["LinkedIn", "LinkedIn Profile URL", "LinkedIn URL"],
               profile.links.get("linkedin")),
        _field(["GitHub", "GitHub Profile"], profile.links.get("github")),
        _field(["Personal Website", "Portfolio", "Website"],
               profile.links.get("portfolio")),

        # Posting-specific.
        _field(["Position", "Role", "Job Title", "Position Applied For"], posting.role),
        _field(["Company"], posting.company),
        _field(["How did you hear about us?", "Source", "Referral Source"],
               {"handshake": "Handshake", "company_site": "Company website",
                "referral": "Referral", "linkedin": "LinkedIn"}.get(posting.source or "")),
    ]

    essays = []
    for key, text in (profile.essays or {}).items():
        if text:
            essays.append({
                "prompt": key.replace("_", " ").rsplit(" ", 1)[0].strip().capitalize(),
                "key": key,
                "answer": str(text).strip(),
            })
    # The answer that is never reused: written by Claude for this posting,
    # audited in the same pass as the letter.
    answers = answers or {}
    essays.append({
        "prompt": "Why are you interested in this role / this firm? (short)",
        "key": "why_this_firm_short",
        "answer": (answers.get("short") or "").strip(),
        "note": "About 80 words. Written for this posting and audited alongside "
                "the letter.",
    })
    essays.append({
        "prompt": "Why are you interested in this role / this firm? (long)",
        "key": "why_this_firm_long",
        "answer": (answers.get("long") or "").strip(),
        "note": "About 200 words. Written for this posting and audited alongside "
                "the letter.",
    })

    return {
        "slug": posting.slug,
        "generated_at": _dt.datetime.now().replace(microsecond=0).isoformat(sep=" "),
        "company": posting.company,
        "role": posting.role,
        "source_url": posting.source_url,
        "fields": [f for f in raw if f],
        "essays": essays,
        "omitted_by_design": [
            "Social Security Number", "Date of Birth", "Driver's License",
            "Passport Number", "Bank account details",
        ],
    }


def write(profile: Profile, posting: Posting, directory: Path,
          answers: dict | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "fieldpack.json"
    path.write_text(json.dumps(build(profile, posting, answers), indent=2) + "\n")
    return path
