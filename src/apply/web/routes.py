"""Routes.

Two of these are different from the rest. /app/{id}/review and /app/{id}/submit
are the dashboard's half of the human gate: they are the only handlers that pass
`via="review"` and `via="submit"` to db.transition, and nothing else in this file
can reach `ready` or `submitted` however it is called.

Nothing here contacts an employer. /app/{id}/submit records that the owner did.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .. import db, digest as digest_mod, generate
from ..models import Status, Track, TransitionError
from ..parse import parse as parse_jd
from ..profile import Profile

router = APIRouter()
BASE = Path(__file__).resolve().parents[3]
templates = Jinja2Templates(directory=str(BASE / "templates"))

MARKABLE = ["acknowledged", "assessment", "interviewing", "offer", "rejected", "withdrawn"]


def _context(page: str, **extra) -> dict:
    """Starlette injects `request` itself under the current signature."""
    return {"page": page, "owner": Profile.load().display_name, **extra}


def _flash(slug: str, message: str, ok: bool = True) -> RedirectResponse:
    query = f"?m={quote(message)}&ok={'1' if ok else '0'}"
    return RedirectResponse(f"/posting/{slug}{query}", status_code=303)


# ------------------------------------------------------------- pipeline


@router.get("/", response_class=HTMLResponse)
def pipeline(request: Request, track: str | None = None):
    conn = db.connect()
    rows = [r for r in db.rows(conn)
            if r.application.status not in ("rejected", "withdrawn")
            and not digest_mod.screened_out(r)]
    by_track = {t.value: sum(1 for r in rows if r.posting.track == t.value) for t in Track}
    current = track if track in by_track else None     # an unknown track shows everything
    if current:
        rows = [r for r in rows if r.posting.track == current]
    return templates.TemplateResponse(
        request,
        "web/pipeline.html",
        _context("pipeline", rows=rows, counts=digest_mod.headline(conn),
                 tracks=by_track, current_track=current),
    )


@router.get("/posting/{slug}", response_class=HTMLResponse)
def detail(request: Request, slug: str, m: str | None = None, ok: str = "1"):
    conn = db.connect()
    row = db.row_for(conn, slug)
    if row is None:
        return RedirectResponse("/", status_code=303)

    directory = generate.out_dir() / slug
    fieldpack = None
    pack_path = directory / "fieldpack.json"
    if pack_path.exists():
        fieldpack = json.loads(pack_path.read_text())

    def _name(path: str | None) -> str | None:
        return Path(path).name if path and Path(path).exists() else None

    audit = None
    audit_path = directory / "verification.json"
    if audit_path.exists():
        try:
            audit = json.loads(audit_path.read_text())
        except ValueError:
            audit = None

    anchors = [
        a.with_article
        for a in generate.jd_anchors(
            row.posting.jd_raw, row.posting.company, row.posting.role, row.posting.location
        )
    ]
    return templates.TemplateResponse(
        request,
        "web/detail.html",
        _context("detail",
            row=row,
            events=db.events(conn, row.application.id),
            fieldpack=fieldpack,
            anchors=anchors,
            letter_name=_name(row.application.letter_path),
            resume_name=_name(row.application.resume_path),
            markable=MARKABLE,
            audit=audit,
            message=m,
            message_ok=(ok == "1"),
        ),
    )


# ---------------------------------------------------------------- intake


@router.get("/add", response_class=HTMLResponse)
def add_form(request: Request, error: str | None = None):
    return templates.TemplateResponse(
        request,
        "web/add.html",
        _context("add", error=error))


@router.post("/add", response_class=HTMLResponse)
def add_parse(request: Request, jd: str = Form(...)):
    if not jd.strip():
        return templates.TemplateResponse(
        request,
        "web/add.html",
        _context("add", error="Nothing to read — paste the posting first."),
        )
    parsed = parse_jd(jd)
    scores = parsed.classification.scores
    return templates.TemplateResponse(
        request,
        "web/confirm.html",
        _context("add",
            parsed=parsed, jd_escaped=jd, notes=parsed.notes,
            tracks=[t.value for t in Track],
            top_score=max(scores.values()) or 1,
        ),
    )


@router.post("/add/create")
def add_create(
    jd: str = Form(...),
    company: str = Form(...),
    role: str = Form(...),
    track: str = Form("corporate"),
    deadline: str = Form(""),
    location: str = Form(""),
    comp: str = Form(""),
    source: str = Form(""),
    source_url: str = Form(""),
    priority: int = Form(3),
):
    import datetime as _dt

    conn = db.connect()
    parsed = parse_jd(jd, source=source or None, source_url=source_url or None)
    parsed.company, parsed.role = company.strip(), role.strip()
    parsed.location = location.strip() or None
    parsed.comp = comp.strip() or None
    parsed.classification.track = Track.parse(track)
    parsed.deadline = _dt.date.fromisoformat(deadline) if deadline else None

    posting = parsed.to_posting()
    posting.priority = priority
    suffix = 2
    base = posting.slug
    while db.get_posting(conn, posting.slug):
        posting.slug = f"{base}-{suffix}"
        suffix += 1
    db.create_posting(conn, posting)
    return _flash(posting.slug, "Added. Generate the letter when you are ready.")


# ----------------------------------------------------------- transitions


@router.post("/app/{app_id}/generate")
def do_generate(app_id: int):
    """Claude writes, a second request audits. Takes a minute; the page waits."""
    from ..budget import Budget, BudgetExceeded
    from ..llm import LLMUnavailable

    conn = db.connect()
    application = db.get_application_by_id(conn, app_id)
    posting = db.get_posting_by_id(conn, application.posting_id)
    profile = Profile.load()
    budget = Budget(conn, caps=(profile.raw.get("budget") or {}))

    try:
        artifacts = generate.build(profile, posting, budget=budget)
    except (BudgetExceeded, LLMUnavailable) as exc:
        return _flash(posting.slug, str(exc).splitlines()[0], ok=False)
    except Exception as exc:  # noqa: BLE001 — surfaced to the owner, not swallowed
        return _flash(posting.slug, f"Could not generate: {exc}", ok=False)

    written = artifacts.written
    if not artifacts.ok:
        db.set_documents(
            conn, app_id,
            resume_variant=application.resume_variant, letter_path=None,
            resume_path=application.resume_path, fieldpack_path=application.fieldpack_path,
        )
        reason = getattr(written, "reason", "") or "; ".join(artifacts.lint.errors)
        db.add_event(conn, app_id, "note", f"not written: {reason[:300]}")
        return _flash(posting.slug,
                      f"No PDF was built — {reason}. The audit is below; the draft is in "
                      f"body.md if you want to fix it by hand.", ok=False)

    db.set_documents(
        conn, app_id,
        resume_variant=artifacts.resume_variant or None,
        letter_path=str(artifacts.letter_pdf) if artifacts.letter_pdf else None,
        resume_path=str(artifacts.resume_pdf) if artifacts.resume_pdf else None,
        fieldpack_path=str(artifacts.fieldpack) if artifacts.fieldpack else None,
    )
    was_ready = application.status == Status.READY.value
    db.transition(conn, app_id, Status.GENERATED, via="gen",
                  detail=f"{artifacts.status}, ${written.cost:.2f} (dashboard)")

    message = (f"Written and audited ({artifacts.status}, ${written.cost:.2f}). "
               f"Read it, then mark it ready.")
    if was_ready:
        message = ("Rewritten, so this went back to `generated` and the earlier review "
                   "was cleared. Read it again.")
    return _flash(posting.slug, message, ok=written.verified)


@router.post("/app/{app_id}/review")
def do_review(app_id: int):
    """The human gate. This is the only route that may write `ready`."""
    conn = db.connect()
    application = db.get_application_by_id(conn, app_id)
    posting = db.get_posting_by_id(conn, application.posting_id)
    letter = Path(application.letter_path) if application.letter_path else None
    if letter is None or not letter.exists():
        return _flash(
            posting.slug,
            "There is no letter to read. Generate one — and clear whatever the "
            "lint reported — before marking this ready.",
            ok=False,
        )
    try:
        db.transition(conn, app_id, Status.READY, via="review",
                      detail="read and approved by the owner (dashboard)")
    except TransitionError as exc:
        return _flash(posting.slug, str(exc), ok=False)
    return _flash(posting.slug, "Marked ready. Submit it in the portal, then record it here.")


@router.post("/app/{app_id}/submit")
def do_submit(app_id: int):
    """Records that the owner submitted. Contacts no one."""
    import datetime as _dt

    conn = db.connect()
    application = db.get_application_by_id(conn, app_id)
    posting = db.get_posting_by_id(conn, application.posting_id)
    try:
        db.transition(conn, app_id, Status.SUBMITTED, via="submit",
                      detail="submitted by the owner in the employer's portal")
    except TransitionError as exc:
        return _flash(posting.slug, str(exc), ok=False)
    due = _dt.date.today() + _dt.timedelta(days=14)
    db.add_followup(conn, app_id, due, f"No reply from {posting.company} — follow up")
    return _flash(posting.slug, f"Recorded. Follow-up queued for {due}.")


@router.post("/app/{app_id}/mark")
def do_mark(app_id: int, status: str = Form(...)):
    conn = db.connect()
    application = db.get_application_by_id(conn, app_id)
    posting = db.get_posting_by_id(conn, application.posting_id)
    try:
        db.transition(conn, app_id, Status(status), via="mark")
    except (TransitionError, ValueError) as exc:
        return _flash(posting.slug, str(exc), ok=False)
    return _flash(posting.slug, f"Recorded: {status}.")


@router.post("/app/{app_id}/folder")
def do_folder(app_id: int):
    conn = db.connect()
    application = db.get_application_by_id(conn, app_id)
    posting = db.get_posting_by_id(conn, application.posting_id)
    directory = generate.out_dir() / posting.slug
    if directory.exists() and sys.platform == "darwin":
        subprocess.run(["open", str(directory)], check=False)
    return _flash(posting.slug, f"Opened {directory.name}.")


# ------------------------------------------------------------- files


@router.get("/file/{slug}/{name}")
def serve_file(slug: str, name: str):
    """Serve one generated file. Resolved and bounds-checked against out/."""
    root = generate.out_dir().resolve()
    try:
        path = (root / slug / name).resolve()
        path.relative_to(root)          # raises if anything escaped out/
    except (ValueError, OSError):
        return RedirectResponse("/", status_code=303)
    if not path.is_file():
        return RedirectResponse("/", status_code=303)
    media = "application/pdf" if path.suffix.lower() == ".pdf" else "text/plain"
    return FileResponse(path, media_type=media,
                        headers={"Content-Disposition": f'inline; filename="{name}"'})


# ------------------------------------------------------------- digest


@router.get("/digest", response_class=HTMLResponse)
def digest_page(request: Request):
    conn = db.connect()
    d = digest_mod.build(conn)

    sections = [
        ("Past due, not submitted", [(r, f"{-r.days_left}d ago") for r in d.overdue]),
        (f"Deadlines in the next {digest_mod.HORIZON_DAYS} days",
         [(r, f"{r.days_left}d") for r in d.deadlines]),
        ("Further out", [(r, f"{r.days_left}d") for r in d.beyond]),
        ("No deadline on file", [(r, "verify") for r in d.unverified]),
        (f"Drafts untouched for {digest_mod.STALE_DAYS}+ days",
         [(r, r.application.status) for r in d.stale]),
        (f"Submitted {digest_mod.SILENT_DAYS}+ days ago, no reply",
         [(r, "nudge?") for r in d.silent]),
    ]
    tracks = sorted(d.tracks.items(), key=lambda kv: -kv[1])
    return templates.TemplateResponse(
        request,
        "web/digest.html",
        _context("digest",
            d=d, counts=digest_mod.headline(conn), sections=sections,
            tracks=tracks, track_max=max(d.tracks.values()) if d.tracks else 1,
        ),
    )
