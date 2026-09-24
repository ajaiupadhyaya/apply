"""The first ten minutes: a profile that is yours, not its author's.

`apply init` used to scaffold from the author's own profile, which meant a
stranger's first act was deleting a biography. The scaffold is now a persona —
a complete fictional person, so the pipeline runs end to end on a fresh clone —
and `apply setup` turns nine answers into a profile of your own.

The persona lends its *shape* and nothing else. A scaffolded profile keeps the
persona's keys, comments' worth of structure and writing brief, and marks every
fact about a life with ASK, because a fact inherited from a fictional person is
still a fact nobody can source.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .generate import repo_root
from .profile import ASK, GRAD_FORMAT, GRAD_SHAPE

EXAMPLE_PROFILE = repo_root() / "data" / "profile.example.yaml"

#: (attribute, question, default). The order the wizard asks in.
QUESTIONS = [
    ("name", "Your full name", ""),
    ("email", "Email for applications", ""),
    ("school", "School or university", ""),
    ("degree", "Degree, e.g. BS Finance", ""),
    ("grad_expected", "Graduation, YYYY-MM", ""),
    ("city", "Where you want to work", ""),
    ("work", "The work you want, in a few words", "research and analysis"),
]

#: How many times a question that will not take a blank is put again before the
#: wizard gives up. A terminal user gets as many tries as they need within this;
#: a non-interactive caller answering the same thing every time gets an error
#: instead of a loop.
MAX_RETRIES = 5


def check_grad_expected(value: str) -> str | None:
    """None if the gate can read this graduation month, else what is wrong.

    Every other answer may be left blank and filled in later, because every
    other answer is only ever printed. This one is computed with: class standing
    and the eligibility window both derive from it, so a blank here is what the
    next command dies on.
    """
    value = (value or "").strip()
    if not value:
        return f"a graduation date is needed — {GRAD_SHAPE}"
    match = GRAD_FORMAT.match(value)
    if not match:
        return f"{value!r} is not {GRAD_SHAPE}"
    if not 1 <= int(match.group(2)) <= 12:
        return f"{match.group(2)!r} is not a month; use 01 to 12"
    return None


#: Answers the wizard will not accept in whatever state the user leaves them.
VALIDATORS = {"grad_expected": check_grad_expected}


@dataclass(slots=True)
class Answers:
    name: str = ""
    email: str = ""
    school: str = ""
    degree: str = ""
    grad_expected: str = ""
    city: str = ""
    work: str = ""
    authorized: bool = True
    sponsorship: bool = False
    links: dict[str, str] = field(default_factory=dict)


def persona() -> dict:
    return yaml.safe_load(EXAMPLE_PROFILE.read_text())


def profile_from(answers: Answers) -> dict:
    """The persona with the answers written over it, and the rest hollowed out.

    The writing brief and the shape of every block are inherited, because they
    are instructions rather than claims. Everything the wizard asks replaces the
    persona's value outright, and everything else — the projects, the skills,
    the job, the availability — becomes ASK, so `apply doctor` lists it rather
    than a letter citing work the persona did.
    """
    data = persona()
    first, last = _split_name(answers.name)
    data["identity"] = {
        "legal_first": first,
        "legal_last": last,
        "preferred_name": first,
        "email": answers.email or ASK,
        "location": _location(answers.city),
    }
    data["links"] = dict(answers.links or {})
    data["education"] = [{
        "institution": answers.school or ASK,
        "degree": answers.degree or ASK,
        "start": ASK,
        "grad_expected": answers.grad_expected or ASK,
        "current": True,
    }]
    data["availability"] = {"full_time": ASK, "internship": ASK}
    data["authorization"] = {
        "us_work_authorized": answers.authorized,
        "requires_sponsorship_now": answers.sponsorship,
        "requires_sponsorship_future": answers.sponsorship,
        "felony": False,
        "veteran": False,
    }
    data["experience"] = [{
        "org": ASK,
        "title": ASK,
        "start": ASK,
        "end": "present",
        "location": ASK,
        "bullets": [ASK],
        "detail": [ASK],
    }]
    data["projects"] = {}
    data["skills"] = {}
    data["essays"] = None
    _clear_proof_assets(data)
    # First key in the file, because YAML comments do not survive a dump and
    # this is the one sentence the reader needs before anything else.
    note = (f"Scaffolded by `apply setup`. Fill in every ASK, add the projects "
            f"you want cited, and read the writing brief at the bottom of this "
            f"file. The work you said you were after: "
            f"{answers.work or 'unstated'}.")
    return {"_note": note, **data}


def write_profile(data: dict, path: Path, *, force: bool = False) -> Path:
    if path.exists() and not force:
        raise FileExistsError(f"{path} exists; pass --force to replace it")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    return path


def copy_persona(path: Path, *, force: bool = False) -> Path:
    """The persona file itself, comments and all.

    `--persona` used to load the YAML and dump it back out, which threw away
    every comment in it — including the header saying that Rae Mercer does not
    exist, which is the one line a reader of that file needs before any other. A
    file that is used unmodified is copied, not round-tripped.
    """
    if path.exists() and not force:
        raise FileExistsError(f"{path} exists; pass --force to replace it")
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(EXAMPLE_PROFILE, path)
    return path


def write_search(answers: Answers, path: Path, *, force: bool = False) -> Path | None:
    """Turn the city answer into the gate's `geography`, or leave a file alone.

    The wizard asks where you want to work and, until this existed, did nothing
    with the answer: the gate went on scoring the places the shipped `geography`
    block names, whatever city the user had just typed into the wizard. Returns
    None when there is already a search.yaml, because that file is the user's own
    and a re-run of setup is not a reason to overwrite it.
    """
    from . import search as search_mod

    if path.exists() and not force:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(search_mod.starter(answers.city, answers.work))
    return path


def city_of(data: dict) -> str:
    """The city out of a loaded profile, as the wizard would have asked for it."""
    location = ((data.get("identity") or {}).get("location") or {})
    city, state = location.get("city"), location.get("state")
    if not city or city == ASK:
        return ""
    return f"{city}, {state}" if state and state != ASK else str(city)


def copy_examples(data: Path, source: Path | None = None) -> list[Path]:
    """Copy each `*.example.yaml` into `data` under its live name, when free.

    `source` defaults to `data`, because in a checkout the examples sit beside
    the files they scaffold. It differs when APPLY_DATA_DIR points elsewhere:
    the examples are shipped with the code, the live files are the user's.
    """
    source = source or data
    created = []
    for example in sorted(source.glob("*.example.yaml")):
        live = data / example.name.replace(".example", "")
        if not live.exists():
            shutil.copyfile(example, live)
            created.append(live)
    return created


def ask(prompt_fn) -> Answers:
    """Put the questions to `prompt_fn(question, default) -> str`.

    The indirection is so the wizard can be tested without a terminal, and so
    the CLI owns every decision about how a prompt looks.
    """
    answers = Answers()
    for attribute, question, default in QUESTIONS:
        value = prompt_fn(question, default).strip() or default
        check = VALIDATORS.get(attribute)
        for _ in range(MAX_RETRIES if check else 0):
            problem = check(value)
            if problem is None:
                break
            value = prompt_fn(f"{question} — {problem}", default).strip() or default
        else:
            if check and (problem := check(value)) is not None:
                raise ValueError(f"{question}: {problem}")
        setattr(answers, attribute, value)
    answers.authorized = _yes(
        prompt_fn("Authorised to work there without sponsorship? [Y/n]", "y"))
    answers.sponsorship = not answers.authorized
    github = prompt_fn("GitHub URL (blank to skip)", "").strip()
    if github:
        answers.links = {"github": github}
    return answers


def _clear_proof_assets(data: dict) -> None:
    """Keep the brief's shape, drop the piece of work it points at.

    `writing.letter.proof_asset` names the default subject of paragraph 2 on
    each track. The persona's answers name the persona's projects, and a brief
    that tells Claude to lead with a library you never wrote is worse than no
    brief at all — so the tracks stay, as empty lines to fill in.
    """
    letter = (data.get("writing") or {}).get("letter") or {}
    if letter.get("proof_asset"):
        letter["proof_asset"] = dict.fromkeys(letter["proof_asset"])


def _yes(value: str) -> bool:
    return not value.strip().lower().startswith("n")


def _split_name(name: str) -> tuple[str, str]:
    """`identity` stores a first and a last name; people type one string."""
    parts = name.split()
    if not parts:
        return ASK, ASK
    if len(parts) == 1:
        return parts[0], ASK
    return parts[0], " ".join(parts[1:])


def _location(city: str) -> dict:
    """'New York, NY' becomes {city, state}; anything else is a city alone."""
    city = city.strip()
    if not city:
        return {"city": ASK}
    head, _, tail = city.partition(",")
    if tail.strip():
        return {"city": head.strip(), "state": tail.strip()}
    return {"city": head.strip()}
