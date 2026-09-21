"""The command line. One command per thing the owner actually does.

Two commands are different from the rest: `review` and `submit`. They are the
only callers allowed to move an application into `ready` and `submitted`, and
both of them stop and ask. Nothing in this file, and nothing anywhere else,
submits an application to an employer.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import (budget as budget_mod, db, digest as digest_mod,
               discover as discover_mod, generate, notify as notify_mod,
               resolve as resolve_mod, run as run_mod, schedule as schedule_mod)
from .models import Posting, Status, Track, TransitionError, slugify
from .parse import parse as parse_jd
from .profile import ASK, Profile, ProfileError, data_dir

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Everything up to the submit button. APPLY never submits an application.",
)
console = Console()

#: Handshake is off limits, by the owner's rule. The account is provisioned by
#: VCU Career Services and automated access risks losing it mid-cycle.
BLOCKED_HOSTS = {"joinhandshake.com", "app.joinhandshake.com", "www.joinhandshake.com"}

HANDSHAKE_MESSAGE = (
    "Handshake postings must be pasted manually — APPLY never logs into or "
    "scrapes Handshake.\n"
    "  Open the posting, select all, copy, then:  apply add --clipboard"
)


# ----------------------------------------------------------------- helpers


def _fail(message: str, code: int = 1) -> None:
    console.print(f"[bold red]✗[/] {message}")
    raise typer.Exit(code)


def _profile() -> Profile:
    try:
        return Profile.load()
    except ProfileError as exc:
        _fail(str(exc))


def _conn():
    path = db.db_path()
    if not path.exists():
        _fail("no database yet. Run `apply init` first.")
    return db.connect(path)


def _row(conn, slug: str):
    row = db.row_for(conn, slug)
    if row is None:
        known = [r.posting.slug for r in db.rows(conn)]
        near = [s for s in known if slug in s]
        hint = f"\n  Did you mean: {', '.join(near[:5])}" if near else ""
        _fail(f"no posting with slug `{slug}`.{hint}")
    return row


STATUS_STYLE = {
    "draft": "dim", "generated": "yellow", "ready": "bold green",
    "submitted": "cyan", "acknowledged": "cyan", "assessment": "magenta",
    "interviewing": "bold magenta", "offer": "bold green",
    "rejected": "dim red", "withdrawn": "dim",
}


def _deadline_text(row) -> Text:
    d = row.posting.deadline
    if d is None:
        return Text("⚠ unverified", style="dim yellow")
    left = row.days_left
    style = "bold red" if left <= 3 else "yellow" if left <= 7 else ""
    suffix = f"  {left}d" if left >= 0 else f"  {-left}d ago"
    return Text(f"{d.isoformat()}{suffix}", style=style)


def _print_lint(artifacts) -> None:
    for error in artifacts.lint.errors:
        console.print(f"  [bold red]lint[/] {error}")
    for warning in artifacts.lint.warnings + artifacts.warnings:
        console.print(f"  [yellow]note[/] {warning}")


def _open_path(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.run(["open", str(path)], check=False)
    elif sys.platform.startswith("linux"):
        subprocess.run(["xdg-open", str(path)], check=False)
    else:
        webbrowser.open(path.as_uri())


# -------------------------------------------------------------------- init


@app.command()
def init(
    force: bool = typer.Option(False, "--force", help="Recreate the schema (data is kept)."),
) -> None:
    """Create apply.db and check the profile."""
    path = db.init_db()
    console.print(f"[green]✓[/] database at [bold]{path}[/]")

    public = data_dir() / "profile.yaml"
    if not public.exists():
        template = Path(__file__).resolve().parents[2] / "data" / "profile.yaml"
        if not template.exists():
            _fail(f"no profile at {public}, and no template to scaffold from.")
        public.parent.mkdir(parents=True, exist_ok=True)
        public.write_text(template.read_text())
        console.print(f"[green]✓[/] scaffolded [bold]{public}[/] — edit it before generating.")

    profile = _profile()
    console.print(f"[green]✓[/] profile for [bold]{profile.display_name}[/] "
                  f"({', '.join(p.name for p in profile.sources)})")

    private = data_dir() / "profile.private.yaml"
    if not private.exists():
        console.print(
            f"[yellow]•[/] no [bold]{private.name}[/] yet. Copy "
            f"[bold]profile.private.example.yaml[/] to it and fill in phone, "
            f"address, and GPA. That file is gitignored."
        )
    doctor()


@app.command()
def doctor() -> None:
    """List every profile value still marked ASK, and check the toolchain."""
    profile = _profile()
    unresolved = profile.unresolved()
    if unresolved:
        console.print("\n[bold]Profile values still marked ASK:[/]")
        for path in unresolved:
            console.print(f"  [yellow]•[/] {path}")
    else:
        console.print("[green]✓[/] no ASK values left in the profile")

    import shutil as _shutil

    if _shutil.which("pdflatex"):
        console.print("[green]✓[/] pdflatex found")
    else:
        console.print("[bold red]✗[/] pdflatex not on PATH — no PDFs can be built.\n"
                      "    brew install --cask mactex-no-gui")

    from . import llm as llm_mod

    if llm_mod.available():
        console.print("[green]✓[/] Anthropic credential present (`--llm=api` available)")
    else:
        console.print("[dim]•[/] no Anthropic credential — `--llm=manual` (the default) "
                      "still works and costs nothing")

    console.print(
        f"\n[dim]sponsorship answer on file: "
        f"{'REQUIRED' if profile.needs_sponsorship_ever else 'not required, now or ever'}[/]"
    )


# --------------------------------------------------------------------- add


@app.command()
def add(
    file: Optional[Path] = typer.Option(None, "--file", "-f", help="Read the JD from a file."),
    stdin: bool = typer.Option(False, "--stdin", help="Read the JD from standard input."),
    clipboard: bool = typer.Option(False, "--clipboard", "-c", help="Read the JD from the clipboard."),
    url: Optional[str] = typer.Option(None, "--url", help="Fetch a company careers page."),
    company: Optional[str] = typer.Option(None, "--company"),
    role: Optional[str] = typer.Option(None, "--role"),
    track: Optional[str] = typer.Option(None, "--track", help="Override the classification."),
    slug: Optional[str] = typer.Option(None, "--slug"),
    deadline: Optional[str] = typer.Option(None, "--deadline", help="ISO date, e.g. 2026-10-14."),
    source: Optional[str] = typer.Option(None, "--source",
                                         help="handshake | company_site | referral | linkedin"),
    priority: int = typer.Option(3, "--priority", min=1, max=5),
) -> None:
    """Add a posting from pasted text, a file, or a company careers page."""
    conn = _conn()
    text, fetched_url = _read_jd(file, stdin, clipboard, url)
    if not text.strip():
        _fail("no job description text found.")

    parsed = parse_jd(text, source=source, source_url=fetched_url)
    if company:
        parsed.company = company
    if role:
        parsed.role = role
    if deadline:
        parsed.deadline = _dt.date.fromisoformat(deadline)
        parsed.notes = [n for n in parsed.notes if "deadline" not in n]
    if track:
        parsed.classification.track = Track.parse(track)
        parsed.classification.tied = False

    if not parsed.complete:
        for note in parsed.notes:
            console.print(f"  [yellow]•[/] {note}")
        _fail("cannot create a posting without a company and a role.")

    posting = parsed.to_posting(slug=slug)
    posting.priority = priority
    if db.get_posting(conn, posting.slug):
        _fail(f"a posting with slug `{posting.slug}` already exists. "
              f"Use --slug to give this one a different name.")

    db.create_posting(conn, posting)

    console.print(Panel.fit(
        f"[bold]{posting.company}[/] — {posting.role}\n"
        f"slug      {posting.slug}\n"
        f"track     {parsed.classification.why}\n"
        f"deadline  {posting.deadline or '[yellow]⚠ not stated — verify manually[/]'}\n"
        f"location  {posting.location or '—'}\n"
        f"comp      {posting.comp or '—'}",
        title="added", border_style="green",
    ))
    if not track:
        table = Table(show_header=True, header_style="dim", box=None, padding=(0, 2))
        table.add_column("track"); table.add_column("score", justify="right"); table.add_column("matched")
        for name, score, matched in parsed.classification.table():
            table.add_row(name, str(score), matched[:70])
        console.print(table)
        console.print(f"[dim]Wrong? apply gen {posting.slug} --track <other>[/]")
    for note in parsed.notes:
        console.print(f"  [yellow]•[/] {note}")
    console.print(f"\nNext: [bold]apply gen {posting.slug}[/]")


def _read_jd(file, stdin, clipboard, url) -> tuple[str, str | None]:
    if url:
        host = (urlparse(url).hostname or "").lower()
        if host in BLOCKED_HOSTS or host.endswith(".joinhandshake.com"):
            _fail(HANDSHAKE_MESSAGE)
        return _fetch(url), url
    if file:
        if not file.exists():
            _fail(f"no such file: {file}")
        return file.read_text(), None
    if clipboard:
        if sys.platform != "darwin":
            _fail("--clipboard is macOS only. Pipe the text in with --stdin instead.")
        out = subprocess.run(["pbpaste"], capture_output=True, text=True)
        return out.stdout, None
    if stdin or not sys.stdin.isatty():
        return sys.stdin.read(), None
    _fail("give me the posting: --file, --stdin, --clipboard, or --url.")


def _fetch(url: str) -> str:
    import re
    from html.parser import HTMLParser

    import httpx

    class Strip(HTMLParser):
        def __init__(self):
            super().__init__()
            self.parts: list[str] = []
            self.skip = 0

        def handle_starttag(self, tag, attrs):
            if tag in ("script", "style", "noscript"):
                self.skip += 1
            elif tag in ("p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4"):
                self.parts.append("\n")

        def handle_endtag(self, tag):
            if tag in ("script", "style", "noscript") and self.skip:
                self.skip -= 1

        def handle_data(self, data):
            if not self.skip and data.strip():
                self.parts.append(data.strip())

    try:
        response = httpx.get(url, follow_redirects=True, timeout=20.0,
                             headers={"User-Agent": "apply/0.1 (personal job tracker)"})
        response.raise_for_status()
    except httpx.HTTPError as exc:
        _fail(f"could not fetch {url}: {exc}\n  Paste the text instead: apply add --clipboard")
    stripper = Strip()
    stripper.feed(response.text)
    return re.sub(r"\n{3,}", "\n\n", " ".join(stripper.parts).replace(" \n ", "\n"))


# --------------------------------------------------------------------- gen


@app.command()
def gen(
    slug: str,
    track: Optional[str] = typer.Option(None, "--track", help="Override the classification."),
    llm: str = typer.Option("manual", "--llm", help="manual | api"),
    from_body: bool = typer.Option(False, "--from-body", help="Render out/<slug>/body.md."),
    to: Optional[str] = typer.Option(None, "--to", help="Address the letter to a person."),
    anchor: Optional[str] = typer.Option(None, "--anchor", help="Force paragraph 4's citation."),
    model: Optional[str] = typer.Option(None, "--model"),
    effort: str = typer.Option("high", "--effort", help="low | medium | high | xhigh | max"),
    no_resume: bool = typer.Option(False, "--no-resume"),
) -> None:
    """Generate the letter, pick the resume variant, and build the field pack."""
    conn = _conn()
    row = _row(conn, slug)
    profile = _profile()
    posting, application = row.posting, row.application

    if track:
        posting.track = Track.parse(track).value
        db.update_posting(conn, posting)
        console.print(f"[dim]track overridden to {posting.track}[/]")

    was_ready = application.status == Status.READY.value
    try:
        artifacts = generate.build(
            profile, posting, llm=llm, from_body=from_body, to=to,
            anchor_override=anchor, model=model, effort=effort, skip_resume=no_resume,
        )
    except (generate.CompileError, FileNotFoundError, KeyError) as exc:
        _fail(str(exc))
    except Exception as exc:  # LLMUnavailable and friends
        _fail(str(exc))

    _print_lint(artifacts)

    if not artifacts.ok:
        # The PDF is gone, so the database must not keep pointing at it.
        db.set_documents(
            conn, application.id,
            resume_variant=application.resume_variant,
            letter_path=None,
            resume_path=application.resume_path,
            fieldpack_path=application.fieldpack_path,
        )
        db.add_event(conn, application.id, "note",
                     "lint refused the letter: " + "; ".join(artifacts.lint.errors))
        console.print(
            f"\n[bold red]No PDF was produced.[/] The lint refused this letter.\n"
            f"  Source written for inspection: {artifacts.letter_tex}"
        )
        raise typer.Exit(1)

    if artifacts.usage is not None:
        console.print(f"  [dim]{artifacts.usage}[/]")

    db.set_documents(
        conn, application.id,
        resume_variant=artifacts.resume_variant or None,
        letter_path=str(artifacts.letter_pdf) if artifacts.letter_pdf else None,
        resume_path=str(artifacts.resume_pdf) if artifacts.resume_pdf else None,
        fieldpack_path=str(artifacts.fieldpack) if artifacts.fieldpack else None,
    )
    db.transition(conn, application.id, Status.GENERATED, via="gen",
                  detail=f"generated from {artifacts.source}")

    anchor_line = artifacts.anchors[0].with_article if artifacts.anchors else "[yellow]none found[/]"
    console.print(Panel.fit(
        f"[bold]{posting.company}[/] — {posting.role}   [dim]({posting.track})[/]\n"
        f"anchor    {anchor_line}\n"
        f"letter    {artifacts.letter_pdf.name}\n"
        f"resume    {artifacts.resume_pdf.name if artifacts.resume_pdf else '—'}"
        f"  [dim]{artifacts.resume_variant}[/]\n"
        f"fieldpack {artifacts.fieldpack.name if artifacts.fieldpack else '—'}\n"
        f"folder    {artifacts.directory}",
        title="generated", border_style="yellow",
    ))
    if was_ready:
        console.print("[yellow]•[/] this application was `ready`; regenerating reset it "
                      "to `generated` and cleared the review. Read it again.")
    if artifacts.prompt_md:
        console.print(
            f"\n[dim]To improve the prose: paste {artifacts.prompt_md.name} into Claude, "
            f"save the result to body.md, then `apply gen {slug} --from-body`.[/]"
        )
    console.print(f"\nNext: [bold]apply review {slug}[/]")


# ------------------------------------------------------------------- check


@app.command()
def check(
    slug: str,
    model: Optional[str] = typer.Option(None, "--model"),
    effort: str = typer.Option("high", "--effort"),
) -> None:
    """Have Claude read the generated letter against the posting and report problems.

    Read-only. It cannot change a status, and its opinion is not a review — you
    still have to read the letter yourself.
    """
    from . import llm as llm_mod

    conn = _conn()
    row = _row(conn, slug)
    profile = _profile()
    body = generate.out_dir() / slug / "cover_letter.tex"
    if not body.exists():
        _fail(f"nothing generated yet. Run `apply gen {slug}` first.")

    letter = generate.compose(profile, row.posting)
    body_md = generate.out_dir() / slug / "body.md"
    if body_md.exists():
        letter = generate.letter_from_body(profile, row.posting, body_md.read_text())

    try:
        result, usage = llm_mod.review(
            profile, row.posting, letter.full_text,
            model=model or llm_mod.DEFAULT_MODEL, effort=effort,
        )
    except llm_mod.LLMUnavailable as exc:
        _fail(str(exc))

    colour = "green" if result.verdict == "send" else "yellow"
    console.print(Panel.fit(f"[bold {colour}]{result.verdict.upper()}[/]",
                            title=f"check — {slug}", border_style=colour))

    if result.unsupported_claims:
        console.print("[bold red]Claims the sources do not support:[/]")
        for claim in result.unsupported_claims:
            console.print(f"  [red]•[/] {claim}")
    for finding in result.findings:
        style = {"blocker": "bold red", "should-fix": "yellow", "nit": "dim"}[finding.severity]
        console.print(f"\n[{style}]{finding.severity}[/] [dim]{finding.where}[/]")
        console.print(f"  {finding.problem}")
        console.print(f"  [green]→[/] {finding.suggestion}")

    console.print(f"\n[dim]strongest: {result.strongest_sentence}[/]")
    console.print(f"[dim]weakest:   {result.weakest_sentence}[/]")
    console.print(f"[dim]{usage}[/]")
    db.add_event(conn, row.application.id, "note",
                 f"llm check: {result.verdict}, {len(result.findings)} findings")


# -------------------------------------------------------------------- show


@app.command()
def show(slug: str, jd: bool = typer.Option(False, "--jd", help="Print the full job description.")) -> None:
    """Print everything known about one posting."""
    conn = _conn()
    row = _row(conn, slug)
    posting, application = row.posting, row.application

    console.print(Panel.fit(
        f"[bold]{posting.company}[/] — {posting.role}\n"
        f"track      {posting.track}\n"
        f"status     [{STATUS_STYLE.get(application.status,'')}]{application.status}[/]\n"
        f"deadline   {posting.deadline or '⚠ not stated'}"
        + (f"   ({row.days_left}d)" if posting.deadline else "") + "\n"
        f"location   {posting.location or '—'}\n"
        f"comp       {posting.comp or '—'}\n"
        f"priority   {posting.priority}\n"
        f"reviewed   {application.reviewed_at or '—'}\n"
        f"submitted  {application.submitted_at or '—'}\n"
        f"url        {posting.source_url or '—'}",
        title=posting.slug, border_style="blue",
    ))

    for label, value in (("letter", application.letter_path),
                         ("resume", application.resume_path),
                         ("fieldpack", application.fieldpack_path)):
        console.print(f"  {label:10} {value or '—'}")

    anchors = generate.jd_anchors(posting.jd_raw, posting.company, posting.role, posting.location)
    if anchors:
        console.print("\n[bold]Anchors in the posting[/] [dim](apply gen --anchor to force one)[/]")
        for a in anchors[:6]:
            console.print(f"  • {a.with_article}")

    events = db.events(conn, application.id)
    if events:
        console.print("\n[bold]Log[/]")
        for e in events:
            console.print(f"  [dim]{e.occurred_at}[/]  {e.kind:12} {e.detail or ''}")

    pending = db.followups(conn, application.id)
    if pending:
        console.print("\n[bold]Follow-ups[/]")
        for f in pending:
            console.print(f"  [dim]{f.due_on}[/]  {f.action}")

    if jd:
        console.print("\n[bold]Job description[/]\n")
        console.print(posting.jd_raw)


# ------------------------------------------------------- review and submit


@app.command()
def review(
    slug: str,
    yes: bool = typer.Option(False, "--yes", help="Skip the prompt (you have already read it)."),
) -> None:
    """Open the letter, then promote generated → ready. This is the human gate."""
    conn = _conn()
    row = _row(conn, slug)
    application = row.application

    if application.status != Status.GENERATED.value:
        _fail(f"`{slug}` is `{application.status}`, not `generated`. "
              f"Only a generated application can be reviewed.")

    # A review gate with nothing to read is not a gate. If the last build failed
    # the lint, or the file was moved, there is nothing here to approve.
    letter = Path(application.letter_path) if application.letter_path else None
    if letter is None or not letter.exists():
        _fail(f"there is no letter to read for `{slug}`. "
              f"Run `apply gen {slug}` and fix whatever the lint reports first.")
    if letter and letter.exists() and not yes:
        console.print(f"opening [bold]{letter.name}[/] …")
        _open_path(letter)
        if application.resume_path and Path(application.resume_path).exists():
            _open_path(Path(application.resume_path))

    console.print(Panel.fit(
        "You are about to mark this letter as read and approved.\n"
        "[dim]Nothing is sent. `ready` only means you have seen the document.[/]",
        title=f"review — {row.posting.company}", border_style="yellow",
    ))
    if not yes and not typer.confirm("Have you read it, and is it correct?", default=False):
        console.print("[dim]left as `generated`.[/]")
        raise typer.Exit(0)

    db.transition(conn, application.id, Status.READY, via="review",
                  detail="read and approved by the owner")
    console.print(f"[bold green]✓[/] `{slug}` is [bold green]ready[/]. "
                  f"Next: [bold]apply submit {slug}[/] — after you submit it yourself.")


@app.command()
def submit(
    slug: str,
    yes: bool = typer.Option(False, "--yes"),
) -> None:
    """Record that YOU submitted this application. APPLY does not submit anything."""
    conn = _conn()
    row = _row(conn, slug)
    application = row.application

    try:
        from .models import check_transition
        check_transition(Status(application.status), Status.SUBMITTED, "submit")
    except TransitionError as exc:
        _fail(str(exc))

    console.print(Panel.fit(
        f"[bold]{row.posting.company}[/] — {row.posting.role}\n\n"
        f"letter  {Path(application.letter_path).name if application.letter_path else '—'}\n"
        f"resume  {Path(application.resume_path).name if application.resume_path else '—'}\n\n"
        "[dim]This records that you submitted the application in the employer's\n"
        "portal. It does not contact the employer.[/]",
        title="submit", border_style="cyan",
    ))
    if not yes and not typer.confirm("Did you submit this yourself, just now?", default=False):
        console.print("[dim]nothing recorded.[/]")
        raise typer.Exit(0)

    db.transition(conn, application.id, Status.SUBMITTED, via="submit",
                  detail="submitted by the owner in the employer's portal")
    due = _dt.date.today() + _dt.timedelta(days=14)
    db.add_followup(conn, application.id, due, f"No reply from {row.posting.company} — follow up")
    console.print(f"[bold cyan]✓[/] recorded. Follow-up queued for [bold]{due}[/].")


@app.command()
def mark(slug: str, status: str, note: Optional[str] = typer.Option(None, "--note")) -> None:
    """Record what happened after you submitted: ack, assessment, interviewing, offer, rejected, withdrawn."""
    conn = _conn()
    row = _row(conn, slug)
    aliases = {"ack": Status.ACKNOWLEDGED, "oa": Status.ASSESSMENT,
               "interview": Status.INTERVIEWING, "reject": Status.REJECTED}
    target = aliases.get(status.lower())
    if target is None:
        try:
            target = Status(status.lower())
        except ValueError:
            _fail(f"unknown status `{status}`. "
                  f"Try: {', '.join(s.value for s in Status)}")
    try:
        db.transition(conn, row.application.id, target, via="mark", detail=note)
    except TransitionError as exc:
        _fail(str(exc))
    console.print(f"[green]✓[/] `{slug}` → [{STATUS_STYLE.get(target.value,'')}]{target.value}[/]")


# ------------------------------------------------------------------ status


@app.command()
def status(all_rows: bool = typer.Option(False, "--all", help="Include closed applications.")) -> None:
    """The pipeline, deadline first."""
    conn = _conn()
    rows = db.rows(conn)
    if not all_rows:
        rows = [r for r in rows if r.application.status not in ("rejected", "withdrawn")]
    if not rows:
        console.print("[dim]nothing in the pipeline. `apply add --clipboard` to start.[/]")
        return

    counts = digest_mod.headline(conn)
    console.print(
        f"[bold red]{counts['due_7']}[/] due ≤7d   "
        f"[yellow]{counts['awaiting_review']}[/] awaiting review   "
        f"[bold green]{counts['ready']}[/] ready to submit   "
        f"[cyan]{counts['submitted_week']}[/] submitted this week\n"
    )

    table = Table(box=None, header_style="dim", padding=(0, 2))
    for column in ("p", "company", "role", "track", "deadline", "status"):
        table.add_column(column, justify="right" if column == "p" else "left")
    for row in rows:
        table.add_row(
            str(row.posting.priority), row.posting.company,
            Text(row.posting.role[:38], overflow="ellipsis"), row.posting.track,
            _deadline_text(row),
            Text(row.application.status, style=STATUS_STYLE.get(row.application.status, "")),
        )
    console.print(table)


@app.command()
def digest(
    days: int = typer.Option(digest_mod.HORIZON_DAYS, "--days",
                             help="Urgency horizon. Deadlines past it still show, quietly."),
) -> None:
    """Deadlines, follow-ups, and stale drafts."""
    conn = _conn()
    digest_mod.render(conn, console, horizon=days)


@app.command(name="open")
def open_folder(slug: str) -> None:
    """Open out/<slug>/ in the file manager."""
    conn = _conn()
    row = _row(conn, slug)
    directory = generate.out_dir() / row.posting.slug
    if not directory.exists():
        _fail(f"nothing generated yet. Run `apply gen {slug}`.")
    _open_path(directory)


@app.command()
def fields(slug: str, plain: bool = typer.Option(False, "--plain", help="label=value, one per line.")) -> None:
    """Print the field pack for copying into a portal."""
    conn = _conn()
    row = _row(conn, slug)
    path = generate.out_dir() / row.posting.slug / "fieldpack.json"
    if not path.exists():
        _fail(f"no fieldpack yet. Run `apply gen {slug}`.")
    pack = json.loads(path.read_text())
    if plain:
        for f in pack["fields"]:
            print(f"{f['labels'][0]}={f['value']}")
        return
    table = Table(box=None, header_style="dim", padding=(0, 2))
    table.add_column("field"); table.add_column("value")
    for f in pack["fields"]:
        table.add_row(f["labels"][0], f["value"])
    console.print(table)
    console.print(f"\n[dim]never asked for, never stored: "
                  f"{', '.join(pack['omitted_by_design'])}[/]")


@app.command()
def followup(
    slug: str,
    action: str = typer.Argument(..., help="What to do."),
    days: int = typer.Option(7, "--in", help="Days from today."),
) -> None:
    """Queue a follow-up."""
    conn = _conn()
    row = _row(conn, slug)
    due = _dt.date.today() + _dt.timedelta(days=days)
    db.add_followup(conn, row.application.id, due, action)
    console.print(f"[green]✓[/] {due}: {action}")


@app.command()
def discover(
    dry_run: bool = typer.Option(False, "--dry-run", help="Score everything; write nothing."),
    hydrate: int = typer.Option(60, "--hydrate", help="Max full descriptions to fetch."),
    show_rejects: bool = typer.Option(False, "--show-rejects", help="Print why things were dropped."),
) -> None:
    """Poll every configured employer and file anything worth reading.

    Costs nothing: no model is called and no document is written. Run it as often
    as you like.
    """
    conn = _conn()
    profile = _profile()
    employers = discover_mod.load_employers()
    preferences = profile.search_preferences

    with console.status(f"polling {len(employers)} employers…"):
        result = discover_mod.run(conn, employers=employers, preferences=preferences,
                                  hydrate_limit=hydrate, dry_run=dry_run)

    for error in result.errors:
        console.print(f"  [yellow]source[/] {error}")

    console.print(
        f"\n[dim]{result.fetched} fetched · {result.unique} unique · "
        f"{result.already_known} already known · {result.hydrated} hydrated · "
        f"{result.rejected} rejected[/]\n"
    )

    if show_rejects and result.rejections:
        table = Table(box=None, header_style="dim", padding=(0, 2))
        table.add_column("reason"); table.add_column("n", justify="right")
        counts: dict[str, int] = {}
        for _, verdict in result.rejections:
            counts[verdict.rejected_by or "score"] = counts.get(verdict.rejected_by or "score", 0) + 1
        for reason, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            table.add_row(reason, str(n))
        console.print(table)
        console.print()

    if not result.worth_reading:
        console.print("[dim]nothing new worth reading.[/]")
        return

    table = Table(box=None, header_style="dim", padding=(0, 2))
    for column in ("score", "", "company", "role", "location", "deadline"):
        table.add_column(column, justify="right" if column == "score" else "left")
    for posting, verdict in result.worth_reading[:40]:
        style = "bold green" if verdict.pursue else "yellow"
        table.add_row(
            str(verdict.value),
            Text(verdict.verdict.value, style=style),
            posting.employer,
            Text((posting.title or "")[:42], overflow="ellipsis"),
            Text((posting.location or "—")[:24], overflow="ellipsis"),
            str(posting.deadline or "—"),
        )
    console.print(table)

    if dry_run:
        console.print("\n[dim]--dry-run: nothing was written.[/]")
        return
    console.print(
        f"\n[green]✓[/] filed {len(result.created)} new "
        f"posting{'' if len(result.created) == 1 else 's'}. "
        f"Next: [bold]apply status[/], then [bold]apply gen <slug>[/]."
    )


@app.command()
def spend(ledger: bool = typer.Option(False, "--ledger", help="Show individual calls.")) -> None:
    """What the model spending has been, and what is left this month."""
    conn = _conn()
    profile = _profile()
    budget = budget_mod.Budget(conn, caps=(profile.raw.get("budget") or {}))
    state = budget.state()

    bar_width = 34
    filled = round(bar_width * min(1.0, state.fraction))
    colour = "red" if state.fraction > 0.85 else "yellow" if state.fraction > 0.6 else "green"
    console.print(
        f"\n[{colour}]{'█' * filled}[/][dim]{'░' * (bar_width - filled)}[/]  {state}\n"
    )

    rows = budget.by_purpose()
    if rows:
        table = Table(box=None, header_style="dim", padding=(0, 2))
        table.add_column("purpose"); table.add_column("calls", justify="right")
        table.add_column("usd", justify="right")
        for purpose, usd, calls in rows:
            table.add_row(purpose, str(calls), f"${usd:.3f}")
        console.print(table)
    else:
        console.print("[dim]no model calls recorded yet.[/]")

    if ledger:
        console.print()
        for row in budget.ledger():
            console.print(
                f"  [dim]{row['occurred_at']}[/]  {row['purpose']:8} {row['model']:18} "
                f"{row['slug'] or '—':34} ${row['usd']:.4f}"
            )
    console.print(
        f"\n[dim]caps: ${budget.caps['per_call_usd']:.2f}/call · "
        f"${budget.caps['per_run_usd']:.2f}/run · "
        f"${budget.caps['monthly_usd']:.2f}/month — edit `budget:` in "
        f"profile.private.yaml[/]"
    )


@app.command(name="run")
def run_once(
    llm: str = typer.Option("manual", "--llm", help="manual (free) | api (spends)"),
    limit: Optional[int] = typer.Option(None, "--limit",
                                        help="Max documents to write. Defaults to max_auto_per_day."),
    no_discover: bool = typer.Option(False, "--no-discover"),
    no_ingest: bool = typer.Option(False, "--no-ingest"),
    hydrate: int = typer.Option(60, "--hydrate"),
    notify: bool = typer.Option(False, "--notify", help="Write the summary and notify."),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """One unattended pass: discover, ingest, write, report.

    This is what the scheduled job runs. It never moves an application past
    `generated` — reading it and submitting it are still yours — and it stops
    before doing anything if data/HALT exists.
    """
    report = run_mod.run(
        llm=llm, generate_limit=limit, discover_postings=not no_discover,
        ingest_mail=not no_ingest, hydrate=hydrate, dry_run=dry_run,
    )

    if report.halted:
        console.print(Panel.fit(
            f"[bold]Halted.[/] {data_dir() / run_mod.HALT_FILE} exists, so nothing ran.\n"
            f"[dim]Remove that file to let runs resume.[/]",
            border_style="red", title="run"))
        raise typer.Exit(0)

    for step in report.steps:
        style = "green" if step.ok else "red"
        console.print(f"  [{style}]{'✓' if step.ok else '✗'}[/] "
                      f"{step.name:10} [dim]{step.detail}[/]")

    console.print(Panel.fit(
        f"{report.discovered} new from the registry · {report.ingested} from alerts\n"
        f"{len(report.generated)} written · {len(report.generation_failed)} refused\n"
        f"${report.usd:.2f} spent · {report.duration:.0f}s",
        title=report.run_id, border_style="cyan"))

    for slug, why in report.generation_failed:
        console.print(f"  [yellow]refused[/] {slug} [dim]{why[:90]}[/]")

    conn = db.connect()
    summary = run_mod.summarise(conn, report)
    if notify:
        profile = _profile()
        topic = (profile.raw.get("notify") or {}).get("ntfy_topic")
        for line in notify_mod.deliver(report, digest_mod.headline(conn), summary,
                                       generate.out_dir(), ntfy_topic=topic):
            console.print(f"  [dim]{line}[/]")
    else:
        console.print(f"\n[dim]{run_mod.summarise(conn, report).splitlines()[2]}[/]")

    counts = digest_mod.headline(conn)
    if counts["awaiting_review"]:
        console.print(f"\nNext: [bold]apply status[/] — "
                      f"{counts['awaiting_review']} awaiting your eyes.")


@app.command()
def schedule(
    install: bool = typer.Option(False, "--install", help="Write and load the LaunchAgent."),
    remove: bool = typer.Option(False, "--remove"),
    show: bool = typer.Option(False, "--show", help="Print the plist without writing it."),
    at: str = typer.Option("06:30", "--at", help="Local time, HH:MM."),
    llm: str = typer.Option("manual", "--llm", help="What the scheduled run uses."),
) -> None:
    """Run the pass every morning, via launchd.

    With no flags this reports what is currently scheduled. `--show` prints the
    file that would be written; `--install` is a separate, explicit act, because
    it is persistent configuration on your machine.
    """
    try:
        hour, minute = (int(part) for part in at.split(":", 1))
    except ValueError:
        _fail(f"--at wants HH:MM, got {at!r}")

    plan = schedule_mod.Schedule(
        hour=hour, minute=minute, project=generate.repo_root(),
        command=f"uv run apply run --notify --llm {llm}",
    )

    if show:
        console.print(plan.render())
        return

    if remove:
        if schedule_mod.remove():
            console.print("[green]✓[/] unloaded and removed.")
        else:
            console.print("[dim]nothing was installed.[/]")
        return

    if install:
        try:
            path = schedule_mod.install(plan)
        except Exception as exc:                        # noqa: BLE001
            _fail(str(exc))
        console.print(Panel.fit(
            f"Runs every day at [bold]{at}[/].\n"
            f"{plan.command}\n\n"
            f"[dim]{path}\n"
            f"logs: {plan.project / 'out' / 'run.log'}[/]",
            title="scheduled", border_style="green"))
        console.print("[dim]Stop it any time with `apply schedule --remove`, or "
                      "pause a single night with `touch data/HALT`.[/]")
        return

    state = schedule_mod.status()
    if not state["installed"]:
        console.print(
            "[dim]nothing scheduled.[/]\n\n"
            "  See what would be installed:  [bold]apply schedule --show[/]\n"
            "  Install it:                   [bold]apply schedule --install --at 06:30[/]"
        )
        return
    console.print(Panel.fit(
        f"every day at [bold]{state['at']}[/]   "
        f"{'[green]loaded[/]' if state['loaded'] else '[red]not loaded[/]'}\n"
        f"[dim]{state['command']}\n{state['path']}\nlogs: {state['log']}[/]",
        title="scheduled", border_style="cyan"))


@app.command()
def runs(limit: int = typer.Option(10, "--limit")) -> None:
    """What the scheduled runs have done."""
    conn = _conn()
    rows = run_mod.history(conn, limit)
    if not rows:
        console.print("[dim]no runs recorded yet.[/]")
        return
    table = Table(box=None, header_style="dim", padding=(0, 2))
    for column in ("started", "found", "alerts", "written", "usd"):
        table.add_column(column, justify="right" if column != "started" else "left")
    for row in rows:
        table.add_row(str(row["started_at"])[:16], str(row["discovered"]),
                      str(row["ingested"]), str(row["generated"]), f"${row['usd']:.2f}")
    console.print(table)


@app.command()
def ingest(
    file: Optional[Path] = typer.Option(None, "--file", "-f",
                                        help="An alert export written by Claude."),
    imap: bool = typer.Option(False, "--imap", help="Read the mailbox directly."),
    user: Optional[str] = typer.Option(None, "--user", help="IMAP address."),
    days: int = typer.Option(30, "--days", help="How far back to read."),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """File the postings out of Handshake's job-alert emails.

    APPLY never fetches a page from Handshake. It reads the mail Handshake
    already sends you, which is a different thing and carries no risk to a
    VCU-provisioned account.

    Two ways in. `--imap` reads the mailbox directly and needs a Gmail app
    password in the ANTHROPIC-style keychain slot APPLY_IMAP_PASSWORD; that is
    the path an unattended run uses. `--file` reads an export, which is how it
    works when Claude does the fetching through the Gmail connector.
    """
    conn = _conn()
    profile = _profile()
    preferences = profile.search_preferences

    if imap:
        import os

        address = user or profile.email
        password = os.environ.get("APPLY_IMAP_PASSWORD", "")
        if not password:
            _fail(
                "no IMAP password. Gmail needs an app password, not your account "
                "password:\n"
                "  1. myaccount.google.com → Security → 2-Step Verification → App passwords\n"
                "  2. security add-generic-password -U -a \"$USER\" -s APPLY_IMAP_PASSWORD -w\n"
                "  3. export APPLY_IMAP_PASSWORD=\"$(security find-generic-password "
                "-a \"$USER\" -s APPLY_IMAP_PASSWORD -w)\"\n"
                "If VCU's Workspace forbids app passwords, ask Claude to export the "
                "alerts instead and use --file."
            )
        try:
            messages = discover_mod.fetch_imap(user=address, password=password, days=days)
        except Exception as exc:                         # noqa: BLE001
            _fail(f"could not read the mailbox: {exc}")
    elif file:
        if not file.exists():
            _fail(f"no such file: {file}")
        messages = discover_mod.load_messages(file)
    else:
        _fail("give me the mail: --imap, or --file <export.json>.")

    result = discover_mod.ingest_alerts(conn, messages, preferences=preferences,
                                        dry_run=dry_run)
    console.print(
        f"\n[dim]{len(messages)} messages read · {result.fetched} carried jobs · "
        f"{result.unique} unique postings · {result.already_known} already known · "
        f"{result.rejected} rejected[/]\n"
    )
    if not result.worth_reading:
        console.print("[dim]nothing new worth reading.[/]")
        return

    table = Table(box=None, header_style="dim", padding=(0, 2))
    for column in ("score", "", "company", "role", "location", "deadline"):
        table.add_column(column, justify="right" if column == "score" else "left")
    for posting, verdict in result.worth_reading[:40]:
        table.add_row(
            str(verdict.value),
            Text(verdict.verdict.value, style="bold green" if verdict.pursue else "yellow"),
            Text(posting.employer[:22], overflow="ellipsis"),
            Text((posting.title or "")[:42], overflow="ellipsis"),
            Text((posting.location or "—")[:22], overflow="ellipsis"),
            str(posting.deadline or "—"),
        )
    console.print(table)
    console.print(
        "\n[dim]Alerts carry no description, so nothing from this channel is "
        "written up automatically — open it in Handshake and paste the full "
        "posting with `apply add --clipboard` when one is worth pursuing.[/]"
    )
    if dry_run:
        console.print("[dim]--dry-run: nothing was written.[/]")
    else:
        console.print(f"\n[green]✓[/] filed {len(result.created)}.")


@app.command()
def resolve(
    url: str = typer.Argument(..., help="A firm's careers page."),
    name: str = typer.Option("New Employer", "--name", help="What to call it in the registry."),
    priority: int = typer.Option(3, "--priority", min=1, max=5),
    check: bool = typer.Option(True, "--check/--no-check", help="Call the board to confirm."),
) -> None:
    """Work out which job board a firm uses, and print the registry entry for it.

    Paste the careers page URL; this reads the page, finds the ATS fingerprint,
    calls the board to confirm it answers, and prints a block to paste into
    data/employers.yaml. No devtools required.
    """
    try:
        found = resolve_mod.resolve(url, check=check, name=name)
    except Exception as exc:                            # noqa: BLE001
        _fail(f"could not read {url}: {exc}")

    if not found:
        _fail(
            f"no job-board fingerprint in {url}.\n"
            f"  That usually means the careers page renders its listings in\n"
            f"  JavaScript. Open the page, click through to an individual job,\n"
            f"  and run `apply resolve` against THAT url instead — the posting\n"
            f"  page almost always carries the board's address."
        )

    for candidate, count in found:
        if not candidate.supported:
            console.print(
                f"  [yellow]•[/] found [bold]{candidate.ats}[/] "
                f"([dim]{candidate.evidence}[/]) — not supported yet, so this firm "
                f"stays a manual paste."
            )
            continue
        if count is None and check:
            console.print(f"  [yellow]•[/] {candidate.ats} [dim]{candidate.evidence}[/] "
                          f"— found, but the board did not answer.")
            continue
        head = f"[green]✓[/] {candidate.ats}"
        if count is not None:
            head += f" — [bold]{count}[/] postings for 'analyst'"
        console.print(f"\n  {head}   [dim]{candidate.evidence}[/]\n")
        console.print("[dim]Paste into data/employers.yaml under `employers:`[/]\n")
        console.print(candidate.as_yaml(name, priority))
        console.print()


@app.command()
def targets() -> None:
    """The employer registry: who gets polled, and how."""
    employers = discover_mod.load_employers()
    if not employers:
        _fail("no employers configured. Copy data/employers.example.yaml to "
              "data/employers.yaml and add your targets.")
    table = Table(box=None, header_style="dim", padding=(0, 2))
    for column in ("pri", "employer", "ats", "board / tenant", "tracks"):
        table.add_column(column, justify="right" if column == "pri" else "left")
    for e in sorted(employers, key=lambda x: (x.get("priority", 3), x["name"])):
        table.add_row(
            str(e.get("priority", 3)), e["name"], e.get("ats", "?"),
            e.get("board") or f"{e.get('tenant','?')}/{e.get('site','?')}",
            ", ".join(e.get("tracks") or []) or "—",
        )
    console.print(table)


@app.command()
def seed() -> None:
    """Load the two seed postings so the pipeline has real data on day one."""
    conn = _conn()
    fixtures = Path(__file__).resolve().parents[2] / "tests" / "fixtures"
    wanted = {
        "blackrock.txt": ("blackrock-analyst-2027", 1),
        "vcimco.txt": ("vcimco-investment-intern-2027", 1),
    }
    for name, (slug, priority) in wanted.items():
        path = fixtures / name
        if not path.exists():
            continue
        if db.get_posting(conn, slug):
            console.print(f"[dim]•[/] {slug} already present")
            continue
        parsed = parse_jd(path.read_text(), source="company_site")
        posting = parsed.to_posting(slug=slug)
        posting.priority = priority
        db.create_posting(conn, posting)
        console.print(f"[green]✓[/] {slug}  [dim]{parsed.classification.why}[/]")
    console.print("\n[dim]Seed postings use representative text, not the live postings. "
                  "Verify against the real listing before applying.[/]")


@app.command()
def serve(
    port: int = typer.Option(8787, "--port"),
    host: str = typer.Option("127.0.0.1", "--host"),
    no_open: bool = typer.Option(False, "--no-open"),
) -> None:
    """Run the dashboard at http://localhost:8787."""
    import uvicorn

    if not no_open:
        webbrowser.open(f"http://{host}:{port}/")
    uvicorn.run("apply.web.app:app", host=host, port=port, log_level="warning")


@app.command()
def rm(slug: str, yes: bool = typer.Option(False, "--yes")) -> None:
    """Delete a posting and its application row. The out/<slug>/ folder is kept."""
    conn = _conn()
    row = _row(conn, slug)
    if not yes and not typer.confirm(
        f"Delete {row.posting.company} — {row.posting.role} from the database?", default=False
    ):
        raise typer.Exit(0)
    db.delete_posting(conn, slug)
    console.print(f"[green]✓[/] removed `{slug}`. Files in out/{slug}/ were left alone.")


if __name__ == "__main__":
    app()
