"""The twelve acceptance tests from the handoff spec, in order.

These are the definition of done. Each one is named after the behaviour it
protects, not the code it happens to touch.
"""

from __future__ import annotations

import ast
import datetime as _dt
import json
import re
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apply import db, digest as digest_mod, generate
from apply.models import Posting, Status, TransitionError
from apply.parse import parse
from conftest import CLEAN, posting_from

needs_latex = pytest.mark.skipif(
    shutil.which("pdflatex") is None, reason="pdflatex is not installed"
)


# 1 --------------------------------------------------------------------
def test_the_allocator_seed_has_the_right_deadline_and_proof(profile, ashcombe_jd):
    """Claude writes the letter now, so what is deterministic — and asserted — is
    the routing: allocator track, the deadline the posting states, and paragraph 2
    assigned to the allocator proof asset rather than the quant one."""
    from apply import writer

    parsed = parse(ashcombe_jd)
    assert parsed.classification.track.value == "allocator"
    assert parsed.deadline == _dt.date(2026, 10, 14)

    _, user = writer.prompts(profile, parsed.to_posting(), [])
    task = user.split("# TASK", 1)[1]
    assert "Rents and Transit" in task and "Vanilla" not in task


# 2 --------------------------------------------------------------------
def test_the_quant_seed_gets_the_quant_project_as_its_proof(profile, quillon_jd):
    from apply import writer

    parsed = parse(quillon_jd)
    assert parsed.classification.track.value == "quant"
    _, user = writer.prompts(profile, parsed.to_posting(), [])
    assert "Vanilla" in user.split("# TASK", 1)[1]


# 3 --------------------------------------------------------------------
@needs_latex
def test_passionate_fails_the_lint_and_produces_no_pdf(profile, ashcombe_jd, fake_claude):
    posting = posting_from(ashcombe_jd)
    directory = generate.out_dir() / posting.slug

    good = generate.build(profile, posting, caller=fake_claude())
    assert good.letter_pdf.exists()

    # Claude writes it with the banned word, three times running.
    fake = fake_claude(packages=[fake_claude.package(
        paragraph_2="I am passionate about institutional investing.")])
    bad = generate.build(profile, posting, caller=fake)
    assert not bad.ok
    assert any("passionate" in e for e in bad.lint.errors)
    assert bad.letter_pdf is None
    assert fake.count("Review") == 0          # never paid to audit a failing draft
    # And the previous PDF is gone, so yesterday's letter cannot look current.
    assert not good.letter_pdf.exists()
    assert not list(directory.glob("*_Cover_Letter_*.pdf"))


# 4 --------------------------------------------------------------------
@needs_latex
def test_an_ampersand_in_a_company_name_compiles(profile, ashcombe_jd, fake_claude):
    posting = posting_from(ashcombe_jd, company="Smith & Co.", slug="smith-co-analyst-2027")
    artifacts = generate.build(profile, posting, caller=fake_claude())
    assert artifacts.ok
    assert generate.page_count(artifacts.letter_pdf) == 1
    assert r"Smith \& Co." in artifacts.letter_tex.read_text()


# 5 --------------------------------------------------------------------
def test_handshake_urls_are_rejected(conn, monkeypatch):
    """The refusal itself, through the command a person would actually type.

    Re-implementing the predicate here — `host in BLOCKED_HOSTS` — would pass
    even if the guard were deleted from the CLI. So this drives `apply add
    --url` and replaces the fetch with something that raises, which means the
    test fails loudly if a blocked URL ever reaches the network.
    """
    from apply import cli

    def never_fetch(url):
        raise AssertionError(f"apply add --url fetched a blocked host: {url}")

    monkeypatch.setattr(cli, "_fetch", never_fetch)

    for url, site in (
        ("https://app.joinhandshake.com/jobs/123", "Handshake"),
        ("https://joinhandshake.com/jobs/123", "Handshake"),
        ("https://www.joinhandshake.com/stu/jobs/9", "Handshake"),
        ("https://www.linkedin.com/jobs/view/3843944532/", "LinkedIn"),
        ("https://uk.linkedin.com/jobs/view/1", "LinkedIn"),
        ("https://www.indeed.com/viewjob?jk=abc", "Indeed"),
        ("https://uk.indeed.com/viewjob?jk=abc", "Indeed"),
    ):
        result = CliRunner().invoke(cli.app, ["add", "--url", url],
                                    catch_exceptions=False)
        assert result.exit_code != 0, f"{url} was not refused\n{result.output}"
        assert site in result.output                 # named, so the user knows why
        assert "--clipboard" in result.output        # and told what to do instead
        assert "--stdin" in result.output

    assert conn.execute("SELECT count(*) FROM posting").fetchone()[0] == 0


def test_a_careers_page_is_still_fetched(conn, monkeypatch):
    """The other half: the block is a list, not a refusal to fetch anything."""
    from apply import cli

    fetched: list[str] = []

    def record(url):
        fetched.append(url)
        return "Acme Capital\nResearch Analyst 2027\n\n" + "Rolling applications. " * 30

    monkeypatch.setattr(cli, "_fetch", record)
    result = CliRunner().invoke(cli.app, ["add", "--url", "https://acme.example.com/jobs/1"],
                                catch_exceptions=False)
    assert result.exit_code == 0, result.output
    assert fetched == ["https://acme.example.com/jobs/1"]


# 6 --------------------------------------------------------------------
def test_submit_is_refused_before_review(conn):
    posting = db.create_posting(conn, Posting(
        slug="acme-analyst-2027", company="Acme", role="Analyst",
        track="corporate", jd_raw="text"))
    application = db.get_application(conn, posting.id)
    db.transition(conn, application.id, Status.GENERATED, via="gen")
    with pytest.raises(TransitionError, match="apply review"):
        db.transition(conn, application.id, Status.SUBMITTED, via="submit")


# 7 --------------------------------------------------------------------
def test_regenerating_a_ready_application_resets_it(conn):
    posting = db.create_posting(conn, Posting(
        slug="acme-analyst-2027", company="Acme", role="Analyst",
        track="corporate", jd_raw="text"))
    application = db.get_application(conn, posting.id)
    db.transition(conn, application.id, Status.GENERATED, via="gen")
    db.transition(conn, application.id, Status.READY, via="review")
    assert db.get_application_by_id(conn, application.id).reviewed_at

    db.transition(conn, application.id, Status.GENERATED, via="gen")
    after = db.get_application_by_id(conn, application.id)
    assert after.status == "generated"
    assert after.reviewed_at is None


# 8 --------------------------------------------------------------------
def test_a_jd_with_no_deadline_gets_null_and_a_warning():
    parsed = parse("Acme Capital Partners\nResearch Associate\n\n"
                   "We review applications on a rolling basis.")
    assert parsed.deadline is None
    assert any("no application deadline" in n for n in parsed.notes)

    posting = parsed.to_posting()
    assert posting.deadline is None


def test_the_dashboard_counts_undated_postings(conn):
    db.create_posting(conn, Posting(slug="a-b-2027", company="A", role="B",
                                    track="corporate", jd_raw="x"))
    assert digest_mod.headline(conn)["no_deadline"] == 1


# 9 --------------------------------------------------------------------
def test_digest_lists_the_allocator_seed_deadline(conn, ashcombe_jd):
    db.create_posting(conn, posting_from(ashcombe_jd, slug="ashcombe-investment-intern-2027"))
    result = digest_mod.build(conn)
    listed = result.overdue + result.deadlines + result.beyond
    assert any(row.posting.slug == "ashcombe-investment-intern-2027" for row in listed)
    assert all(row.posting.deadline == _dt.date(2026, 10, 14) for row in listed)


# 10 -------------------------------------------------------------------
def test_the_stylesheet_defines_dark_mode_and_a_narrow_breakpoint():
    css = (generate.repo_root() / "src" / "apply" / "web" / "static" / "apply.css").read_text()
    assert "@media (prefers-color-scheme: dark)" in css
    assert ':root:not([data-theme="light"])' in css
    assert ':root[data-theme="dark"]' in css
    assert "@media (max-width: 46rem)" in css      # 736px, covers a 390px phone
    assert "prefers-reduced-motion" in css
    assert "overflow-x: hidden" in css


# Beyond the spec, but the same class of guarantee -----------------------
@needs_latex
def test_a_hand_written_body_with_no_key_is_built_on_the_lint_alone(profile, ashcombe_jd):
    """The one exception to "a lint or audit failure means no PDF", pinned.

    `apply gen <slug> --from-body` with no credential is the owner's own prose
    with nothing to audit it: the lint and the one-page check are all that stand
    between body.md and a PDF. That is deliberate — it is the path that keeps a
    keyless user working — but it is an exception to the promise table, so the
    README carries the caveat and this test carries the behaviour. If the audit
    ever becomes mandatory here, both change together.
    """
    posting = posting_from(ashcombe_jd)
    directory = generate.out_dir() / posting.slug
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "body.md").write_text("\n\n".join(
        [CLEAN["paragraph_1"], CLEAN["paragraph_2"], CLEAN["paragraph_3"],
         CLEAN["paragraph_4"], CLEAN["closing"]]) + "\n")
    (directory / "answers.md").write_text(
        "## Why this role (short)\n\n" + CLEAN["why_role_short"]
        + "\n\n## Why this role (long)\n\n" + CLEAN["why_role_long"] + "\n")

    # No caller and no credential: conftest's tripwire fails the test if either
    # the writer or the auditor reaches the API.
    artifacts = generate.build(profile, posting, llm="manual", from_body=True)

    assert artifacts.written.status == "unverified"
    assert artifacts.written.review is None                 # nothing audited it
    assert artifacts.letter_pdf is not None and artifacts.letter_pdf.exists()
    record = json.loads(artifacts.verification.read_text())
    assert record["status"] == "unverified" and record["verdict"] is None
    assert "not audited" in record["reason"]

    # And the lint still refuses: the exception is the audit, never the lint.
    (directory / "body.md").write_text("\n\n".join(
        [CLEAN["paragraph_1"], "I am passionate about institutional investing.",
         CLEAN["paragraph_3"], CLEAN["paragraph_4"], CLEAN["closing"]]) + "\n")
    refused = generate.build(profile, posting, llm="manual", from_body=True)
    assert not refused.written.ok
    assert refused.letter_pdf is None
    assert not list(directory.glob("*_Cover_Letter_*.pdf"))


def test_the_readme_states_the_exception_to_the_no_pdf_promise():
    """The promise table and the code say the same thing.

    A reader of "Either failure means no PDF" has no way to know that the
    hand-written path builds on the lint alone, so the row says so.
    """
    readme = (generate.repo_root() / "README.md").read_text()
    row = next(line for line in readme.splitlines()
               if line.startswith("| Claim what you haven't done"))
    assert "--from-body" in row and "unverified" in row


def test_no_browser_automation_exists_anywhere():
    """The machinery that would make submitting possible is simply absent.

    This is the load-bearing guarantee: there is no driver, no click, no form
    submission in the codebase, so no bug and no future edit can accidentally
    fire one.
    """
    import re
    from apply.outbound import FORBIDDEN_MACHINERY

    offenders = []
    for path in (generate.repo_root() / "src").rglob("*.py"):
        if path.name == "outbound.py":
            continue                      # the file that declares the list
        text = path.read_text().lower()
        for needle in FORBIDDEN_MACHINERY:
            if needle in text:
                offenders.append(f"{path.name}: {needle}")
        if re.search(r"\.click\s*\(", text):
            offenders.append(f"{path.name}: .click(")
    assert offenders == [], f"submission machinery found: {offenders}"


#: Every shape that can put bytes on a wire.
#:
#: This used to key on the receiver's name — it saw `httpx.post(...)` and
#: `client.post(...)` and missed `session.post(...)`, which is the commonest
#: spelling in Python — so a new module could submit an application and pass the
#: suite by choosing a different local variable. It is written here as shapes
#: instead: an attribute-style send whatever the object is called, a method
#: named in a string, an import of a library whose whole purpose is to send, and
#: a shell-out to curl or wget.
_SENDS = (
    re.compile(r"\.\s*(?:post|put|patch|delete|send|sendall|sendmail|send_message"
               r"|request|stream|upload|submit)\s*\("),
    re.compile(r"\b(?:urlopen|urlretrieve|create_connection)\s*\("),
    re.compile(r"""\brequest\s*\(\s*["'](?:GET|POST|PUT|PATCH|DELETE)""", re.IGNORECASE),
    re.compile(r"^\s*(?:import|from)\s+(?:httpx|requests|aiohttp|httpcore|urllib3|pycurl"
               r"|websocket|websockets|socket|smtplib|ftplib|imaplib|poplib|telnetlib"
               r"|paramiko|anthropic|openai|http\.client|urllib\.request)\b"),
    re.compile(r"""\b(?:curl|wget)\b|["'](?:gh|nc|ssh|scp|rsync)["']"""),
)


def _sending_line(source: str) -> str | None:
    """The first line of `source` that can send something, or None."""
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("@"):
            continue          # a route decorator receives a request, it does not send one
        if any(pattern.search(line) for pattern in _SENDS):
            return stripped
    return None


def _undeclared_senders(package_root: Path, declared) -> dict[str, str]:
    """Modules under `package_root` that can send and are not in `declared`."""
    offenders = {}
    for path in sorted(package_root.rglob("*.py")):
        line = _sending_line(path.read_text())
        if line is None:
            continue
        parts = path.relative_to(package_root).with_suffix("").parts
        module = ".".join((package_root.name, *parts)).replace(".__init__", "")
        if module not in declared:
            offenders[module] = line
    return offenders


def test_every_outbound_call_site_is_declared():
    """A request from an undeclared module fails the suite.

    Discovery is made of network calls, so "makes no requests" is the wrong
    invariant. The right one is that every place that can send anything is
    listed in apply.outbound with a reason it is not an employer.
    """
    from apply.outbound import ALLOWED

    offenders = _undeclared_senders(generate.repo_root() / "src" / "apply", ALLOWED)
    assert offenders == {}, (
        f"these modules send requests but are not declared in apply.outbound: {offenders}")


def test_the_outbound_check_catches_an_undeclared_sender(tmp_path):
    """The tripwire, tripped.

    A guard nobody has ever seen fail is a guard nobody knows works. Each module
    below is a realistic way to submit an application; every one of them slipped
    past the previous version of this check.
    """
    package = tmp_path / "apply"
    (package / "sources").mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package / "sources" / "__init__.py").write_text("")

    senders = {
        "session": "def submit(session, url, form):\n    return session.post(url, data=form)\n",
        "private": "class Portal:\n    def submit(self, url):\n        return self._client.patch(url)\n",
        "verb": 'def submit(http, url):\n    return http.request("POST", url)\n',
        "chained": "import x\n\n\ndef submit(url):\n    return x.Client().put(url)\n",
        "asyncio": "import aiohttp\n\n\nasync def submit(url):\n    ...\n",
        "shell": ('import subprocess\n\n\ndef submit(url):\n'
                  '    subprocess.run(["curl", "-X", "POST", url])\n'),
        "raw": "from urllib.request import urlopen\n\n\ndef submit(url):\n    return urlopen(url)\n",
        "declared": "import httpx\n\n\ndef search(url):\n    return httpx.get(url)\n",
    }
    for name, source in senders.items():
        (package / "sources" / f"{name}.py").write_text(source)
    (package / "quiet.py").write_text("def slugify(text):\n    return text.lower()\n")
    (package / "web.py").write_text(
        '@router.post("/add")\ndef add(request):\n    return render(request)\n')

    offenders = _undeclared_senders(package, {"apply.sources.declared": ((), "declared")})

    assert set(offenders) == {f"apply.sources.{name}" for name in senders} - {
        "apply.sources.declared"}
    assert "apply.quiet" not in offenders       # nothing here sends
    assert "apply.web" not in offenders         # a route decorator is not a call site


def test_every_declared_module_actually_sends():
    """The allow-list stays honest in the other direction too.

    A declaration nothing lives up to is a hole: it lets a future module be
    named `apply.notify` and send anywhere. Every entry must correspond to a
    module that really does make requests.
    """
    from apply.outbound import ALLOWED

    root = generate.repo_root() / "src" / "apply"
    silent = [module for module in ALLOWED
              if _sending_line((root / (module.removeprefix("apply.").replace(".", "/")
                                        + ".py")).read_text()) is None]
    assert silent == [], f"declared in apply.outbound but sends nothing: {silent}"


def test_no_employer_facing_host_is_allowed():
    """Nothing in the allow-list is an application portal."""
    from apply.outbound import ALLOWED

    portals = ("workday.com/apply", "myworkdayjobs.com/apply", "joinhandshake",
               "greenhouse.io/applications", "lever.co/apply")
    for hosts, reason in ALLOWED.values():
        assert reason.strip(), "every allowed host needs a stated reason"
        for host in hosts:
            assert not any(p in host for p in portals), host


# ------------------------------------------------------- credentials
#
# The previous version of this check read every line naming ANTHROPIC_API_KEY
# and passed if the line held "environ", a "#" or a quote — which any line
# naming the key by a literal necessarily does, so `Path("k.txt").write_text(
# lookup("ANTHROPIC_API_KEY"))` passed it. What follows asks what the code
# *does* with a secret rather than which words the line contains.

#: The credentials this system reads. None of them may reach a file.
CREDENTIALS = {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "APPLY_IMAP_PASSWORD"}

#: Calls that return a secret. `lookup(x)` returns one whatever x is, so the
#: call itself is the read — no need to resolve the argument.
SECRET_READERS = {"lookup", "get_password", "_from_keychain", "_from_keyring"}

#: Calls that put bytes somewhere they outlive the process.
WRITE_SINKS = {"write", "write_text", "write_bytes", "writelines", "writerow",
               "writerows", "dump", "dumps", "writestr", "setex", "put"}

#: Parameters that hold a secret by the time they are passed.
SECRET_PARAMETERS = {"password", "passwd", "api_key", "apikey", "auth_token",
                     "token", "secret", "credential"}


def _call_name(node: ast.Call) -> str:
    func = node.func
    return func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")


def _is_environ(node: ast.AST) -> bool:
    return ((isinstance(node, ast.Attribute) and node.attr == "environ")
            or (isinstance(node, ast.Name) and node.id == "environ"))


def _is_a_secret_name(key: ast.AST | None) -> bool:
    """A named credential, or a name we cannot resolve — which counts too."""
    if key is None or not isinstance(key, ast.Constant):
        return True                                      # os.environ[whatever]
    return key.value in CREDENTIALS


def _reads_a_secret(node: ast.AST) -> bool:
    """Whether this expression evaluates to a credential, or to os.environ."""
    settled: set[int] = set()                            # environ nodes with a key attached
    for child in ast.walk(node):
        if isinstance(child, ast.Call) and _call_name(child) in SECRET_READERS:
            return True
        if isinstance(child, ast.Subscript) and _is_environ(child.value):
            settled.add(id(child.value))
            if _is_a_secret_name(child.slice):
                return True
        elif isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute) \
                and child.func.attr in ("get", "pop") and _is_environ(child.func.value):
            settled.add(id(child.func.value))
            if _is_a_secret_name(child.args[0] if child.args else None):
                return True
        elif isinstance(child, ast.Call) and _call_name(child) == "getenv":
            if _is_a_secret_name(child.args[0] if child.args else None):
                return True
    # os.environ passed around whole carries every credential in it.
    return any(_is_environ(child) and id(child) not in settled for child in ast.walk(node))


def _credential_writes(source: str) -> list[str]:
    """Every place in `source` where a credential could reach a file."""
    tree = ast.parse(source)

    tainted: set[str] = set(
        name for node in ast.walk(tree)
        if isinstance(node, ast.arg) and node.arg in SECRET_PARAMETERS
        for name in [node.arg])
    for node in ast.walk(tree):                          # x = secrets.lookup(...)
        value = getattr(node, "value", None)
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.NamedExpr)) and value is not None \
                and _reads_a_secret(value):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            tainted |= {t.id for t in targets if isinstance(t, ast.Name)}

    def carries_a_secret(node: ast.AST) -> bool:
        if _reads_a_secret(node):
            return True
        return any(isinstance(child, ast.Name) and child.id in tainted
                   for child in ast.walk(node))

    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node) not in WRITE_SINKS:
            continue
        arguments = list(node.args) + [keyword.value for keyword in node.keywords]
        if any(carries_a_secret(argument) for argument in arguments):
            offenders.append(f"line {node.lineno}: {_call_name(node)}(...)")
    return offenders


def test_no_credential_is_ever_written_to_disk():
    """A key may be read at call time; it may never be persisted."""
    offenders = []
    for path in sorted((generate.repo_root() / "src").rglob("*.py")):
        offenders += [f"{path.name} {where}" for where in _credential_writes(path.read_text())]
    assert offenders == [], f"a credential reaches a file: {offenders}"


def test_the_credential_check_catches_code_that_writes_one():
    """The tripwire, tripped. Every snippet below passed the old check."""
    hostile = {
        "write_text": 'Path("/tmp/k.txt").write_text(lookup("ANTHROPIC_API_KEY"))',
        "open for writing": 'open("cache.json", "w").write(os.environ["ANTHROPIC_API_KEY"])',
        "single quotes": "open('cache.json','w').write(os.environ.get('ANTHROPIC_API_KEY'))",
        "json": 'json.dump({"key": secrets.lookup("ANTHROPIC_API_KEY")}, handle)',
        "the whole environment": "json.dump(dict(os.environ), handle)",
        "through a variable": ('key = secrets.lookup("ANTHROPIC_API_KEY")\n'
                               'Path("k.txt").write_text(key)\n'),
        "interpolated": ('token = os.environ["ANTHROPIC_AUTH_TOKEN"]\n'
                         'handle.write(f"auth={token}\\n")\n'),
        "the imap password": ('password = secrets.lookup("APPLY_IMAP_PASSWORD")\n'
                              'Path("mail.log").write_text(password)\n'),
        "a parameter": "def cache(path, password):\n    path.write_text(password)\n",
    }
    for name, source in hostile.items():
        assert _credential_writes(source), f"missed: {name}"

    innocent = (
        'def lookup(name):\n'
        '    return os.environ.get(name)\n'
        'Path("verification.json").write_text(json.dumps(record))\n'
        'console.print(secrets.how_to_store("ANTHROPIC_API_KEY"))\n'
        'Path(os.environ["APPLY_DATA_DIR"], "db").write_text(schema)\n'
        'handle.write(os.getenv("APPLY_OUT_DIR", ""))\n'
    )
    assert _credential_writes(innocent) == []


def test_the_secrets_module_never_persists_what_it_reads():
    """apply.secrets is the one door every credential comes through.

    It reads from the environment, the Keychain and a keyring, and holds none of
    them: no file is opened, nothing is cached on the module, so a second call
    goes back to the store rather than to something left lying around.
    """
    source = (generate.repo_root() / "src" / "apply" / "secrets.py").read_text()
    tree = ast.parse(source)

    writes = [f"line {node.lineno}: {_call_name(node)}" for node in ast.walk(tree)
              if isinstance(node, ast.Call)
              and _call_name(node) in WRITE_SINKS | {"open", "mkdir", "touch"}]
    assert writes == [], f"apply.secrets writes: {writes}"

    caches = [node.lineno for node in ast.walk(tree)
              if isinstance(node, (ast.Global, ast.Nonlocal))]
    assert caches == [], f"apply.secrets keeps a secret on the module: {caches}"
