"""What Claude is allowed to know about the owner, and nothing more.

Two sources, both owner-controlled:

  profile.yaml      the facts: education, experience, projects, skills, and the
                    writing brief — instructions about voice and emphasis, never
                    sentences to paste
  data/context/     longer source material: project READMEs, a bio, notes. Plain
                    markdown the owner drops in or pulls from GitHub.

Everything a letter asserts must be traceable to one of these or to the posting.
The deterministic lint enforces that for figures; the verifier enforces it for
everything else. So what goes into this folder is, in effect, the list of things
a letter is allowed to claim — curate it.

Deliberately withheld from the model: phone, street address and GPA. A letter
does not need them, and the principle is to send the API only what the task
requires.
"""

from __future__ import annotations

import base64
import json
import re
import subprocess
from pathlib import Path

from .profile import ASK, Profile, data_dir

#: Per document and in total. Context is cached, so a large block costs little
#: after the first call in a run — but the first call pays for all of it.
MAX_DOC_CHARS = 14_000
MAX_TOTAL_CHARS = 42_000


def context_dir() -> Path:
    return data_dir() / "context"


# ------------------------------------------------------------- the profile


def _month_year(value) -> str | None:
    if value in (None, "", ASK):
        return None
    text = str(value)
    if text.lower() in ("present", "current"):
        return "present"
    m = re.match(r"^(\d{4})-(\d{1,2})", text)
    if not m:
        return text
    months = ["January", "February", "March", "April", "May", "June", "July",
              "August", "September", "October", "November", "December"]
    return f"{months[int(m.group(2)) - 1]} {m.group(1)}"


def authorization_statement(profile: Profile) -> str:
    """The one sentence that must be exactly right in every application."""
    if not profile.work_authorized:
        return "Not currently authorized to work in the United States."
    if profile.needs_sponsorship_ever:
        return ("Authorized to work in the United States; will require employment "
                "sponsorship.")
    return ("Authorized to work in the United States. Will not require employment "
            "sponsorship, now or in the future.")


def render_profile(profile: Profile) -> str:
    """The factual profile as plain labelled text."""
    out = ["# PROFILE", ""]
    out.append(f"Name: {profile.display_name} (legal name {profile.legal_name})")
    if profile.location_line:
        out.append(f"Based in: {profile.location_line}")
    for label, url in (profile.links or {}).items():
        out.append(f"{label.capitalize()}: {url}")
    out.append(f"Work authorization: {authorization_statement(profile)}")
    availability = {k: v for k, v in (profile.raw.get("availability") or {}).items()
                    if v and v != ASK}
    if availability:
        for kind, when in availability.items():
            out.append(f"Availability ({kind.replace('_', '-')}): {when}")
    else:
        # Said explicitly, because an absent fact invites the writer to supply one.
        out.append("Availability: not stated. Do not give a start date or availability.")
    out.append(f"Class standing: {profile.class_standing} "
               f"(graduates {profile.grad_month_year})")

    out += ["", "## Education"]
    for e in profile.education:
        line = f"- {e.get('institution', '')}"
        if e.get("degree"):
            line += f", {e['degree']}" + (f" in {e['major']}" if e.get("major") else "")
        if e.get("current"):
            line += f" — expected {profile.grad_month_year}"
        out.append(line)
        if e.get("note"):
            out.append(f"  {e['note']}")

    out += ["", "## Experience"]
    for x in profile.experience:
        start, end = _month_year(x.get("start")), _month_year(x.get("end"))
        dates = " – ".join(d for d in (start, end) if d) or "dates not recorded"
        out.append(f"- {x.get('title', '')}, {x.get('org', '')} ({dates})"
                   + (f", {x['location']}" if x.get("location") else ""))
        for b in x.get("bullets") or []:
            out.append(f"  - {re.sub(chr(10) + r'|\s+', ' ', b).strip()}")
        for d in x.get("detail") or []:
            out.append(f"  - {re.sub(r'\s+', ' ', d).strip()}")

    out += ["", "## Projects"]
    for p in profile.projects.values():
        head = f"- {p.name}"
        if p.stack:
            head += f" ({', '.join(p.stack)})"
        if p.url:
            head += f" — {p.url}"
        out.append(head)
        if p.tracks:
            out.append(f"  Suited to: {', '.join(p.tracks)}")
        for text in (p.three_line, p.technical):
            if text:
                out.append("  " + re.sub(r"\s+", " ", text).strip())

    skills = {k: v for k, v in (profile.raw.get("skills") or {}).items() if v}
    if skills:
        out += ["", "## Skills"]
        out += [f"- {group}: {', '.join(items)}" for group, items in skills.items()]
    return "\n".join(out)


# ------------------------------------------------------------ the brief


def brief(profile: Profile) -> dict:
    return profile.raw.get("writing") or {}


def render_brief(profile: Profile) -> str:
    """The owner's instructions about voice and emphasis, verbatim."""
    import yaml

    data = brief(profile)
    if not data:
        return "# WRITING BRIEF\n\n(none supplied — use the hard rules alone)"
    return "# WRITING BRIEF\n\n" + yaml.safe_dump(data, sort_keys=False, width=88,
                                                  allow_unicode=True).strip()


def proof_asset(profile: Profile, track: str) -> str | None:
    """The owner's default subject for paragraph 2 on this track."""
    return ((brief(profile).get("letter") or {}).get("proof_asset") or {}).get(track)


# ------------------------------------------------------------ documents


def load_documents(directory: Path | None = None) -> list[tuple[str, str]]:
    """Every markdown file in data/context/, capped, in name order."""
    directory = directory or context_dir()
    if not directory.exists():
        return []
    docs, total = [], 0
    for path in sorted(directory.glob("*.md")):
        if path.name.lower() == "readme.md":
            continue                      # the folder's own instructions
        text = path.read_text(errors="replace").strip()
        if not text:
            continue
        text = text[:MAX_DOC_CHARS]
        if total + len(text) > MAX_TOTAL_CHARS:
            text = text[: max(0, MAX_TOTAL_CHARS - total)]
        if text:
            docs.append((path.stem, text))
            total += len(text)
        if total >= MAX_TOTAL_CHARS:
            break
    return docs


def source_material(profile: Profile) -> str:
    """The shared, cached block: facts, brief, and documents.

    Identical for the writer and the verifier and for every posting in a run,
    which is what lets it be cached once and read cheaply afterwards.
    """
    parts = [render_profile(profile), "", render_brief(profile)]
    docs = load_documents()
    if docs:
        parts += ["", "# CONTEXT DOCUMENTS",
                  "Longer source material supplied by the owner. Facts here may be "
                  "cited; anything absent from here, the profile and the posting may not."]
        for name, text in docs:
            parts += ["", f"## document: {name}", text]
    return "\n".join(parts)


def sourced_text(profile: Profile) -> str:
    """Everything the hallucination guard should treat as a source."""
    return "\n".join([render_profile(profile), *(t for _, t in load_documents())])


# ------------------------------------------------------- pulling a README


def digest_markdown(text: str, limit: int = MAX_DOC_CHARS, *, opening: int = 700) -> str:
    """Keep a long README's shape in its author's own words.

    The introduction survives whole; every heading survives; each section keeps
    its opening. Nothing is paraphrased, so nothing is invented — a 112K-char
    README becomes about 14K of the owner's own sentences.
    """
    text = re.sub(r"```.*?```", "", text, flags=re.S)          # code is not context
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)            # images
    text = re.sub(r"\[\]\([^)]*\)", "", text)                   # badges left empty
    parts = re.split(r"(?m)^(?=#{1,3} )", text)

    kept: list[str] = []
    for index, part in enumerate(parts):
        part = part.strip()
        if not part:
            continue
        if index == 0 or not part.startswith("#"):
            kept.append(part[: opening * 3])                    # the introduction
            continue
        heading, _, body = part.partition("\n")
        body = re.sub(r"\n{3,}", "\n\n", body.strip())
        first = body.split("\n\n", 1)[0] if body else ""
        if len(first) > opening:
            first = first[:opening].rsplit(" ", 1)[0] + " …"
        kept.append(f"{heading}\n{first}".strip())

    digest = "\n\n".join(kept)
    return digest[:limit].rsplit("\n", 1)[0] if len(digest) > limit else digest


def pull_readme(repo: str, *, name: str | None = None) -> Path:
    """Fetch a GitHub repo's README with the gh CLI, digest it, file it.

    Read-only GET through the owner's own gh session. The file records where it
    came from, so a stale one can be recognised and refreshed.
    """
    result = subprocess.run(["gh", "api", f"repos/{repo}/readme"],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"could not read {repo}")
    payload = json.loads(result.stdout)
    raw = base64.b64decode(payload.get("content", "")).decode("utf-8", "replace")
    digest = digest_markdown(raw)

    directory = context_dir()
    directory.mkdir(parents=True, exist_ok=True)
    stem = (name or repo.split("/")[-1]).lower()
    path = directory / f"{re.sub(r'[^a-z0-9_-]+', '-', stem)}.md"
    header = (f"<!-- source: https://github.com/{repo} — README, digested: intro, "
              f"every heading, and each section's opening. {len(raw):,} chars -> "
              f"{len(digest):,}. Re-pull to refresh. -->\n\n")
    path.write_text(header + digest + "\n")
    return path
