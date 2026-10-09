"""`apply setup`: from a fresh clone to a configured pipeline, by asking.

Every step is resumable and re-runnable (`apply setup --step <name>`). Nothing
is written until the user accepts it; nothing existing is replaced without a
backup and a yes — except a file still byte-identical to its shipped example,
which was never the user's. The wizard writes configuration only: it cannot
move an application, and it never submits anything.
"""

from __future__ import annotations

import datetime as _dt
import getpass
import json
import math
import re
import secrets as _random
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

import yaml
from rich.markup import escape as _esc
from rich.text import Text

from . import draft as D
from . import extract

STEPS = ("toolchain", "key", "about", "documents", "draft", "review", "employers", "extras", "finish")

#: Setup may redraft several times (redo with a note), so its run ceiling is
#: higher than a nightly run's. The per-call ceiling is draft.propose's business.
SETUP_PER_RUN_USD = 5.00


class Asker(Protocol):
    def text(self, prompt: str, default: str | None = None) -> str: ...
    def secret(self, prompt: str) -> str: ...
    def confirm(self, prompt: str, default: bool = True) -> bool: ...
    def choice(self, prompt: str, options: list[str], default: str | None = None) -> str: ...
    def edit(self, text: str) -> str | None: ...
    def say(self, markup: str) -> None: ...


class ConsoleAsker:
    def __init__(self, console):
        self.console = console

    def text(self, prompt, default=None):
        from rich.prompt import Prompt
        return Prompt.ask(Text(prompt), default=default or "", console=self.console).strip()

    def secret(self, prompt):
        return getpass.getpass(f"{prompt}: ").strip()

    def confirm(self, prompt, default=True):
        from rich.prompt import Confirm
        return Confirm.ask(Text(prompt), default=default, console=self.console)

    def choice(self, prompt, options, default=None):
        from rich.prompt import Prompt
        return Prompt.ask(Text(prompt), choices=options, default=default, console=self.console)

    def edit(self, text):
        import click
        return click.edit(text, extension=".yaml")       # $EDITOR, or Notepad on Windows

    def say(self, markup):
        self.console.print(markup)


# ------------------------------------------------------------- files and state

def _state_path(data: Path) -> Path:
    return data / ".setup_state.json"


def _draft_path(data: Path) -> Path:
    return data / ".setup_draft.json"


def _load_state(data: Path) -> dict:
    path = _state_path(data)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"done": []}


def _save_state(data: Path, state: dict) -> None:
    data.mkdir(parents=True, exist_ok=True)
    _state_path(data).write_text(json.dumps(state, indent=1), encoding="utf-8")


def _backup(data: Path, path: Path) -> Path:
    # Microseconds, and a counter besides: two backups in one second must
    # never land in the same folder and overwrite the first.
    stamp = _dt.datetime.now().strftime("%Y%m%dT%H%M%S%f")
    target = data / ".backup" / stamp / path.relative_to(data)
    n = 1
    while target.exists():
        target = data / ".backup" / f"{stamp}-{n}" / path.relative_to(data)
        n += 1
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, target)
    return target


def _is_untouched(path: Path, example: Path | None) -> bool:
    return (example is not None and example.exists() and path.exists()
            and path.read_text(encoding="utf-8") == example.read_text(encoding="utf-8"))


def _write_file(data: Path, rel: str, text: str, asker: Asker, *, example: Path | None = None) -> bool:
    path = data / rel
    if path.exists():
        current = path.read_text(encoding="utf-8")
        if current == text:
            return True
        if not _is_untouched(path, example):
            if not asker.confirm(f"{rel} already exists. Back it up and replace it?", default=False):
                asker.say(f"[dim]kept your {_esc(rel)}[/]")
                return False
            asker.say(f"[dim]backed up to {_esc(str(_backup(data, path)))}[/]")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return True


HEADER = "# Written by `apply setup`. Edit freely; `apply doctor` checks it.\n"


def _dump(body: dict) -> str:
    return yaml.safe_dump(body, sort_keys=False, allow_unicode=True)


def _write_yaml(data: Path, rel: str, body: dict, asker: Asker, **kw) -> bool:
    return _write_file(data, rel, HEADER + _dump(body), asker, **kw)


def _ask_clean(asker: Asker, prompt: str, default: str | None = None) -> str:
    """Free text, refusing anything that looks like an SSN or a date of birth."""
    while True:
        answer = asker.text(prompt, default)
        if not extract.contains_forbidden(answer):
            return answer
        asker.say("[bold red]APPLY never stores an SSN or a date of birth[/] — no field it fills "
                  "needs one. Leave it out and answer again.")


def _examples() -> Path:
    from . import EXAMPLE_PROFILE
    return EXAMPLE_PROFILE.parent


def _private_base(data: Path) -> dict:
    """The private file as it stands. The untouched example lends its shape but
    not its invented target firms."""
    path = data / "profile.private.yaml"
    if not path.exists():
        return {}
    body = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if _is_untouched(path, _examples() / "profile.private.example.yaml"):
        body.pop("targets", None)
    return body


def _merge_private(data: Path, overlay: dict) -> None:
    """Add keys to profile.private.yaml without asking: a merge loses nothing
    the user wrote, but YAML comments do not survive it, so it is backed up."""
    from ..profile import deep_merge

    path = data / "profile.private.yaml"
    body = deep_merge(_private_base(data), overlay)
    if path.exists():
        _backup(data, path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HEADER + _dump(body), encoding="utf-8")


def _known(body: dict) -> dict:
    """The keys of a nested dict whose value is not ASK."""
    from ..profile import ASK

    out = {}
    for key, value in body.items():
        if isinstance(value, dict):
            value = _known(value)
            if value:
                out[key] = value
        elif value != ASK:
            out[key] = value
    return out


def _need(state: dict, key: str, step: str) -> None:
    if not state.get(key):
        raise SystemExit(f"run `uv run apply setup --step {step}` first.")


def _answers(state: dict) -> D.Answers:
    _need(state, "answers", "about")
    return D.Answers(**state["answers"])


def _load_draft(data: Path) -> D.Draft:
    path = _draft_path(data)
    if not path.exists():
        raise SystemExit("no draft yet: run `uv run apply setup --step draft` first.")
    return D.Draft.model_validate_json(path.read_text(encoding="utf-8"))


def _split(text: str) -> list[str]:
    return [part.strip() for part in (text or "").split(",") if part.strip()]


# ------------------------------------------------------------------- steps

def _toolchain(ctx: dict) -> None:
    from .. import generate

    asker = ctx["asker"]
    asker.say("[bold]1. Toolchain[/]")
    if shutil.which("pdflatex"):
        asker.say("[green]✓[/] pdflatex found: letters and resumes will compile to PDF.")
    else:
        asker.say("[yellow]•[/] pdflatex is not installed. Everything but the PDFs works without it. "
                  f"To get it:\n    {_esc(generate.tex_hint())}")
    if generate.miktex_autoinstall() is False:
        asker.say("[yellow]•[/] MiKTeX asks before installing a package, and that dialog hangs an "
                  "unattended run. Turn it off:\n    " + _esc("initexmf --set-config-value=[MPM]AutoInstall=1"))


def _key(ctx: dict) -> None:
    import os

    from .. import llm, secrets

    asker, state = ctx["asker"], ctx["state"]
    asker.say("[bold]2. Anthropic API key[/]\nClaude reads your resume and drafts your profile, "
              "and later writes each letter. The key goes to your operating system's credential "
              "store — never to a file in this folder. Get one at console.anthropic.com.")
    if os.environ.get("ANTHROPIC_API_KEY"):
        asker.say("[dim]An exported ANTHROPIC_API_KEY is set in this shell; it wins over a stored key.[/]")
    while True:
        existing = secrets.lookup("ANTHROPIC_API_KEY")
        prompt = "Paste your Anthropic API key" + (" (Enter to keep the stored one)" if existing else "")
        key = asker.secret(prompt).strip()
        if not key and not existing:
            asker.say("[yellow]A key is needed for this step.[/]")
            continue
        if key:
            try:
                secrets.store("ANTHROPIC_API_KEY", key)
            except Exception as exc:                     # noqa: BLE001 — no keyring backend, locked store
                asker.say(f"[red]Could not store the key:[/] {_esc(str(exc))}\nStore it yourself, then press "
                          f"Enter here:\n    {_esc(secrets.how_to_store('ANTHROPIC_API_KEY'))}")
                continue
        try:
            llm.ping()
        except llm.LLMUnavailable as exc:
            asker.say(f"[red]✗[/] {_esc(str(exc))}")
            continue
        asker.say("[green]✓[/] the key works.")
        break
    while True:
        ceiling = asker.text("Monthly spending ceiling in USD (Enter for $15)", "").strip().lstrip("$")
        if not ceiling:
            break
        try:
            dollars = float(ceiling)
        except ValueError:
            dollars = -1.0
        if math.isfinite(dollars) and dollars > 0:
            state["budget"] = {"monthly_usd": dollars}
            break
        asker.say(f"[yellow]{_esc(repr(ceiling))} is not a positive number of dollars.[/]")


def _about(ctx: dict) -> None:
    from . import check_grad_expected

    asker, state = ctx["asker"], ctx["state"]
    asker.say("[bold]3. About you[/]\nWhat you are looking for decides which postings the gate "
              "keeps. Plain answers are fine; you approve everything before it is written.")

    def clean(prompt):
        return _ask_clean(asker, prompt).strip()

    roles = clean("What kinds of roles are you after?")
    kind = asker.choice("Internship, full-time, or both?", ["internship", "full-time", "both"], "both")
    job_types = ["internship", "full-time"] if kind == "both" else [kind]
    locations = _split(clean("Where, most wanted first? (comma-separated)"))
    remote_ok = asker.confirm("Is remote OK?", True)
    firms = _split(clean("Firms you most want (comma-separated; Enter to skip)"))
    avoid = clean("Firms or kinds of work to avoid (Enter to skip)")
    links = {}
    for key, label in (("linkedin", "LinkedIn"), ("github", "GitHub"), ("portfolio", "Portfolio")):
        url = clean(f"{label} URL (Enter to skip)")
        if url:
            links[key] = url
    extra = clean("Anything else a cover letter should know about you? (Enter to skip)")
    authorized = asker.confirm("Are you authorized to work in the US?", True)
    now = asker.confirm("Do you need visa sponsorship now?", False)
    future = asker.confirm("Will you need sponsorship in the future?", now)
    student = asker.confirm("Are you currently a student?", True)
    while True:
        grad = clean("Graduation date, YYYY-MM (expected, or when you graduated)")
        problem = check_grad_expected(grad)
        if problem is None:
            break
        asker.say(f"[yellow]{_esc(problem)}[/]")
    full_time = clean("When are you available full-time? (Enter to skip)") or None
    internship = clean("Internship availability (Enter to skip)") or None
    asker.say("[dim]The next three go only into the private file and onto your resume; "
              "they are never sent to Claude.[/]")
    phone = clean("Phone, for your resume header (Enter to skip)") or None
    street = clean("Street address (Enter to skip)") or None
    gpa = clean("GPA (Enter to skip)") or None
    state["answers"] = asdict(D.Answers(
        roles=roles, job_types=job_types, locations=locations, remote_ok=remote_ok, firms=firms,
        avoid=avoid, links=links, extra=extra, work_authorized=authorized, sponsorship_now=now,
        sponsorship_future=future, grad_expected=grad, student=student,
        availability_full_time=full_time, availability_internship=internship,
        phone=phone, street_address=street, gpa=gpa))


DOCUMENTS = (
    ("resume", "Path to your resume (PDF, DOCX, TXT or MD)", True),
    ("cover_letter", "Path to a cover letter you liked (Enter to skip)", False),
    ("other", "Path to other writing — a project write-up or portfolio page (Enter to skip)", False),
)


def _documents(ctx: dict) -> None:
    asker, state, data = ctx["asker"], ctx["state"], ctx["data"]
    answers = _answers(state)
    asker.say("[bold]4. Your documents[/]\nClaude drafts from these and nothing else. Your phone, "
              "street address and anything like an SSN are taken out before they are saved.")
    texts = []
    for name, prompt, required in DOCUMENTS:
        while True:
            raw = asker.text(prompt, "").strip().strip("'\"")
            if not raw:
                if required:
                    asker.say("[yellow]A resume is needed — it is what the draft is made from.[/]")
                    continue
                break
            path = Path(raw).expanduser()
            if not path.is_file():
                asker.say(f"[yellow]No file at {_esc(str(path))}.[/]")
                continue
            try:
                text = extract.read_document(path)
            except extract.Unreadable as exc:
                asker.say(f"[yellow]{_esc(str(exc))}[/]")
                continue
            clean = extract.redact(text, phone=answers.phone, address=answers.street_address)
            asker.say(f"[green]✓[/] {_esc(path.name)}: {len(clean.split())} words")
            _write_file(data, f"context/{name}.md",
                        f"<!-- source: {path.name}, imported by apply setup -->\n\n{clean}\n", asker)
            texts.append(clean)
            break
    state["sources"] = "\n\n".join(texts)


def _draft(ctx: dict, note: str = "") -> D.Draft:
    from .. import budget, db, llm

    asker, state, data = ctx["asker"], ctx["state"], ctx["data"]
    answers = _answers(state)
    _need(state, "sources", "documents")
    if ctx.get("conn") is None:
        db.init_db(data / "apply.db")
        ctx["conn"] = db.connect(data / "apply.db")
    # The owner's own ceilings first, then this setup's answer.
    caps = {**budget.DEFAULTS, **(_private_base(data).get("budget") or {}), **(state.get("budget") or {})}
    caps["per_run_usd"] = max(caps["per_run_usd"], SETUP_PER_RUN_USD)
    if ctx.get("budget") is None:
        ctx["budget"] = budget.Budget(ctx["conn"], caps=caps)
    if not note:
        asker.say("[bold]5. The draft[/]\nOne request to Claude (about $0.10–0.30). It proposes; "
                  "a check then removes anything your documents do not support.")
    try:
        # The request itself is sent by apply.llm (draft.propose calls llm.call).
        proposed = D.propose(state["sources"], answers, note=note, budget=ctx["budget"])
    except (llm.LLMUnavailable, budget.BudgetExceeded) as exc:
        asker.say(f"[red]✗[/] {_esc(str(exc))}")
        raise SystemExit("the draft did not run; `uv run apply setup` resumes here.") from exc
    grounded, notes = D.ground(proposed, state["sources"], answers, note=note)
    for line in notes:
        asker.say(f"[yellow]•[/] {_esc(line)}")
    _draft_path(data).write_text(grounded.model_dump_json(indent=1), encoding="utf-8")
    return grounded


#: Which top-level keys of profile.yaml each review section shows. `search`
#: is the whole of search.yaml.
VIEWS = {
    "identity": ("identity", "links", "education", "availability", "authorization"),
    "experience": ("experience",),
    "projects": ("projects",),
    "skills": ("skills",),
    "writing": ("writing",),
}


def _view(files: dict, section: str) -> dict:
    if section == "search":
        return files["search.yaml"]
    return {k: files["profile.yaml"].get(k) for k in VIEWS[section]}


def _replace(files: dict, section: str, body: dict) -> None:
    if section == "search":
        files["search.yaml"] = body
        return
    for key in VIEWS[section]:
        if key in body:
            files["profile.yaml"][key] = body[key]


def _to_files(draft: D.Draft, answers: D.Answers) -> dict:
    try:
        return D.to_files(draft, answers)
    except ValueError as exc:
        raise SystemExit(f"{exc}: run `uv run apply setup --step draft`.") from exc


def _review(ctx: dict) -> None:
    from .. import budget
    from . import copy_examples

    asker, state, data = ctx["asker"], ctx["state"], ctx["data"]
    answers = _answers(state)
    draft = _load_draft(data)
    files = _to_files(draft, answers)
    copy_examples(data, _examples())
    asker.say("[bold]6. Review[/]\nEach section in turn: accept it, edit it in your editor, or "
              "tell Claude what to change.")
    for section in D.SECTIONS:
        while True:
            shown = _dump(_view(files, section))
            asker.say(f"\n[bold]{section}[/]\n{_esc(shown)}")
            pick = asker.choice(f"{section}: accept, edit, or redo with a note?",
                                ["accept", "edit", "redo"], "accept")
            if pick == "accept":
                break
            if pick == "edit":
                edited = asker.edit(shown)
                if edited is None:
                    continue
                try:
                    body = yaml.safe_load(edited) or {}
                except yaml.YAMLError as exc:
                    asker.say(f"[red]That is not valid YAML:[/] {_esc(str(exc))}")
                    continue
                if not isinstance(body, dict):
                    asker.say("[red]That is not a block of keys; nothing changed.[/]")
                    continue
                _replace(files, section, body)
                continue
            note = _ask_clean(asker, "What should change?").strip()
            if not note:
                continue
            draft = _draft(ctx, note=f"[{section}] {note}")
            _replace(files, section, _view(_to_files(draft, answers), section))

    examples = _examples()
    _write_yaml(data, "profile.yaml", files["profile.yaml"], asker, example=examples / "profile.example.yaml")
    _write_yaml(data, "search.yaml", files["search.yaml"], asker)
    from ..profile import deep_merge

    # An unanswered private question must not overwrite a value already on
    # file, and a ceiling the owner raised by hand stays raised.
    private = deep_merge({"budget": dict(budget.DEFAULTS)}, _private_base(data))
    private = deep_merge(private, _known(files["profile.private.yaml"]))
    private = deep_merge(private, {"budget": state.get("budget") or {}})
    _write_yaml(data, "profile.private.yaml", private, asker,
                example=examples / "profile.private.example.yaml")
    state["employers"] = [e.model_dump() for e in draft.employers]


def _employers(ctx: dict) -> None:
    from .. import resolve

    asker, state, data = ctx["asker"], ctx["state"], ctx["data"]
    asker.say("[bold]7. Employers[/]\nFinding each firm's job board, so discovery can poll it.")
    draft = _load_draft(data) if _draft_path(data).exists() else None
    terms = [r.match for r in draft.roles[:4]] if draft and draft.roles else ["analyst", "intern"]
    default_track = (draft.default_track.strip().lower() if draft else "") or "default"
    wanted = list(state.get("employers") or
                  ([e.model_dump() for e in draft.employers] if draft else []))
    named = {w["name"].lower() for w in wanted}
    for firm in (state.get("answers") or {}).get("firms") or []:
        if firm.lower() not in named:
            wanted.append({"name": firm, "aliases": [], "tracks": [default_track], "priority": 2})
            named.add(firm.lower())

    example = _examples() / "employers.example.yaml"
    path = data / "employers.yaml"
    entries = []
    if path.exists() and not _is_untouched(path, example):
        entries = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("employers") or []
    have = {str(e.get("name", "")).lower() for e in entries}
    unresolved = []
    for firm in wanted:
        name = firm["name"]
        if name.lower() in have:
            continue
        tracks = [t.strip().lower() for t in firm.get("tracks") or []] or [default_track]
        found = None
        hit = resolve.probe_slugs(name)
        if hit is not None:
            candidate, count = hit
            where = "/".join(str(v) for v in candidate.config.values())
            if asker.confirm(f"Use {candidate.ats}:{where} for {name} ({count} open postings)?", True):
                found = candidate
        if found is None:
            url = asker.text(f"Careers page for {name}? (URL, or Enter to skip)", "").strip()
            if url:
                try:
                    results = resolve.resolve(url, name=name)
                except Exception as exc:                 # noqa: BLE001 — network, HTTP status
                    asker.say(f"[yellow]Could not read that page:[/] {_esc(str(exc))}")
                    results = []
                for candidate, count in results:
                    if candidate.supported and count:
                        asker.say(f"[green]✓[/] {_esc(name)}: {_esc(candidate.ats)} ({count} open postings)")
                        found = candidate
                        break
        if found is None:
            unresolved.append(name)
            continue
        entry = found.as_entry(name, int(firm.get("priority") or 2), terms, tracks)
        if firm.get("aliases"):
            entry["aliases"] = list(firm["aliases"])
        entries.append(entry)
    _write_yaml(data, "employers.yaml", {"employers": entries}, asker, example=example)
    for name in unresolved:
        asker.say(f"[yellow]•[/] {_esc(name)}: no board found. Its postings still arrive through job-alert "
                  "mail (`apply ingest`), and `apply add --clipboard` files any one you find; "
                  f"`apply resolve <careers-url> --name \"{_esc(name)}\"` adds it later.")


def _extras(ctx: dict) -> None:
    from .. import generate, schedule, secrets

    asker, data = ctx["asker"], ctx["data"]
    asker.say("[bold]8. Extras[/] — each optional.")
    if asker.confirm("Read Handshake or LinkedIn job-alert mail from Gmail? (needs a Gmail app password)",
                     False):
        user = _ask_clean(asker, "Gmail address").strip()
        if user:
            _merge_private(data, {"imap": {"user": user}})
        password = asker.secret("Gmail app password (myaccount.google.com/apppasswords)")
        if password:
            try:
                secrets.store("APPLY_IMAP_PASSWORD", password.replace(" ", ""))
                asker.say("[green]✓[/] stored in your OS credential store. `apply ingest --imap` reads it.")
            except Exception as exc:                     # noqa: BLE001
                asker.say(f"[red]Could not store it:[/] {_esc(str(exc))}\n    "
                          f"{_esc(secrets.how_to_store('APPLY_IMAP_PASSWORD'))}")
    if asker.confirm("Push notifications to your phone via ntfy.sh?", False):
        topic = "apply-" + _random.token_urlsafe(12)
        _merge_private(data, {"notify": {"ntfy_topic": topic}})
        asker.say(f"[green]✓[/] subscribe to [bold]{topic}[/] in the ntfy app. Anyone with the "
                  "name can read it, so keep it to yourself.")
    if asker.confirm("Run the discovery pass automatically every morning?", False):
        while True:
            at = asker.text("At what time? (HH:MM, Enter for 06:30)", "").strip() or "06:30"
            match = re.fullmatch(r"(\d{1,2}):(\d{2})", at)
            if match and int(match.group(1)) < 24 and int(match.group(2)) < 60:
                break
            asker.say(f"[yellow]{_esc(repr(at))} is not HH:MM.[/]")
        plan = schedule.Schedule(int(match.group(1)), int(match.group(2)), project=generate.repo_root(),
                                 command="uv run apply run --notify --llm api")
        try:
            schedule.install(plan)
            asker.say(f"[green]✓[/] the morning run is scheduled for {plan.at}.")
        except Exception as exc:                         # noqa: BLE001 — the supervisor refused
            asker.say(f"[red]Could not schedule it:[/] {_esc(str(exc))}. `apply schedule --install` tries again.")


def _finish(ctx: dict) -> None:
    ctx["asker"].say(
        "[bold]Done.[/] Five commands carry the rest:\n"
        "  uv run apply discover          find new postings at your firms\n"
        "  uv run apply status            the pipeline, deadline first\n"
        "  uv run apply gen <slug>        Claude writes and audits the letter\n"
        "  uv run apply review <slug>     you read it: generated → ready\n"
        "  uv run apply submit <slug>     you submitted it yourself: ready → submitted\n"
        "APPLY never submits an application — that click is always yours.\n"
        "Try it now: [bold]uv run apply discover --dry-run[/]")


RUNNERS = {
    "toolchain": _toolchain, "key": _key, "about": _about, "documents": _documents,
    "draft": _draft, "review": _review, "employers": _employers, "extras": _extras,
    "finish": _finish,
}


def run_wizard(asker: Asker, *, step: str | None = None, data: Path | None = None) -> None:
    from ..profile import data_dir

    data = data or data_dir()
    if step is not None and step not in RUNNERS:
        asker.say(f"[red]unknown step {_esc(repr(step))}[/]; one of: {', '.join(STEPS)}")
        raise SystemExit(2)
    state = _load_state(data)
    ctx = {"asker": asker, "data": data, "state": state}
    todo = [step] if step else [s for s in STEPS if s not in state["done"] or s == "finish"]
    try:
        for name in todo:
            RUNNERS[name](ctx)
            if name not in state["done"]:
                state["done"].append(name)
            _save_state(data, state)
    finally:
        if ctx.get("conn") is not None:
            ctx["conn"].close()
