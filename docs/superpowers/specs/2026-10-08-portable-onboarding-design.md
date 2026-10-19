# Portable APPLY: Windows support and first-run onboarding

Date: 2026-10-08 · Branch: `portable-onboarding`

## Intent

**What the owner said.** A friend on Windows is going to try APPLY. Two outcomes:

1. The whole project runs and is fully functional on a PC.
2. The friend clones a repo, gets walked through setup, and is asked for his
   documents (resume, cover letter), an API key, and his goals in a short blurb
   (positions, firms, job type, portfolio). The app then configures itself to
   those answers: profile, search criteria, target employers, alert mail. After
   that it should feel like his own tool.

The owner is the main user and keeps everything they have configured. The friend
uses Cursor, not Claude Code, and will have his own Anthropic API key. His field
is unknown, so everything field-specific has to be configurable.

**Decisions already made.**

- One codebase on `main`. Personal configuration moves out of code and out of
  version control. No long-lived "generic" branch.
- The friend gets a **fresh repo with clean history**, exported from `main`,
  that contains none of the owner's data.
- The setup wizard runs inside the app (`apply setup`) and calls the API itself.
- `keyring` is approved as a new runtime dependency for credential storage.

**Assumptions** (flag any that are wrong):

- The friend's machine is Windows 10 or 11 with PowerShell 5+ and `winget`.
- He may or may not be a student. Career stage comes from the wizard, not from
  code.
- The owner's behaviour must not change. With the owner's current files, every
  score, track and letter comes out the same as today.

**Success criteria.**

- `uv run pytest` passes on `windows-latest` and `macos-latest` in CI, PDF tests
  included.
- On a clean Windows machine: install script → `apply setup` → `apply discover`
  → `apply gen <slug> --llm api` → `apply serve` all work, and `apply schedule
  --install` creates a working daily task.
- The exported repo contains no owner data. A test greps for it.
- The owner's golden scoring corpus (`tests/fixtures/score_corpus.local.json`,
  local only) scores identically before and after.

## Non-goals

- No GUI installer and no web-based wizard. The wizard is a terminal flow.
- No new job sources. ATS adapters and alert parsing stay as they are.
- No change to the safety rules: nothing submits, nothing reaches `ready` or
  `submitted` without a human, and nothing unsourced reaches a document.
- No Linux scheduling. Linux keeps its current partial support.

---

## Part 1 — Windows support

### 1.1 A host layer: `src/apply/host.py`

Every OS-specific operation moves into one module with a function per concern.
Callers stop branching on `sys.platform` themselves.

| Function | macOS | Windows | Linux |
|---|---|---|---|
| `open_path(p)` | `open` | `os.startfile` | `xdg-open` |
| `clipboard_text()` | `pbpaste` | `powershell -NoProfile -Command Get-Clipboard -Raw` | `xclip`/`wl-paste` if present |
| `banner(title, body)` | `osascript` (unchanged) | PowerShell WinRT toast (no module needed) | no-op |
| `get_secret(name)` / `set_secret(name, value)` | see 1.2 | see 1.2 | `keyring` |

Callers that change: `cli.py` (open, clipboard, doctor hints), `web/routes.py`
(open folder), `notify.py` (banner), `llm.py` and `run.py` (secrets).

### 1.2 Credentials

- **Windows and Linux:** `keyring`, which uses Windows Credential Manager on
  Windows. Service names stay `ANTHROPIC_API_KEY` and `APPLY_IMAP_PASSWORD`;
  the account is the OS user.
- **macOS:** the existing `security find-generic-password` path stays first.
  A Keychain item created by the `security` tool trusts only that tool, so
  reading it through Python's `keyring` would raise an access prompt and break
  the 06:30 unattended run. `keyring` is the fallback only.
- **Lookup order everywhere:** environment variable → OS store. The key is
  never written to disk by APPLY.
- `apply setup` and the `doctor` hints write keys with `set_secret`, prompting
  with `getpass`, so a key never appears in shell history.

### 1.3 Scheduling: `schedule.py` gets a second backend

- **macOS:** launchd, unchanged. The label stays `com.ajaiupadhyaya.apply` so
  the owner's installed agent is not orphaned.
- **Windows:** Task Scheduler, through `schtasks /Create /XML` so the task can
  set `StartWhenAvailable` (catch-up after sleep) and `RunOnlyIfNetworkAvailable`.
  - The action runs `uv run apply run --notify --llm <mode>` with the repo as
    the working directory, and writes its log under `out/`.
  - It runs as the user, interactive-token only, so no stored password is
    needed and Credential Manager is readable.
- `--show`, `--install --at HH:MM`, `--remove` and the status view work on
  both backends.
- Task name: `APPLY daily run`.

### 1.4 Text encoding

- Every `read_text`, `write_text` and `open` in `src/` passes
  `encoding="utf-8"` (18 sites).
- A test greps `src/` for any call without it, so the bug cannot come back.
- Subprocess output from `pdflatex` is decoded with `errors="replace"`.

### 1.5 TeX on Windows

- `generate.py` and `doctor` print OS-appropriate install hints:
  - Windows: `winget install MiKTeX.MiKTeX`
  - macOS: `brew install --cask mactex-no-gui`
- `doctor` checks MiKTeX's on-the-fly package install setting and prints the
  one command that enables it. `mathptmx`, `microtype`, `titlesec` and
  `enumitem` are not all in MiKTeX's basic install, and a prompt dialog would
  hang an unattended run.
- Paths passed to `pdflatex` are already plain filenames run from `cwd`; this
  will be verified in Windows CI.

### 1.6 Bootstrap scripts

- **`scripts/install.ps1`**, for Windows:
  1. Checks for and installs, via `winget`, git, uv and MiKTeX, after asking.
  2. Enables MiKTeX auto-install.
  3. Runs `uv sync --all-extras`.
  4. Starts `uv run apply setup`.
  5. Is idempotent: re-running it skips whatever is already present.
- **`scripts/install.sh`** does the same on macOS (Homebrew, uv, MacTeX).

### 1.7 CI: `.github/workflows/test.yml`

- Runs `uv run pytest -q` on a matrix of `windows-latest` and `macos-latest`.
- Installs MiKTeX on Windows so the PDF tests run instead of skipping.
- This is the evidence for "works on a PC": the owner has no Windows machine.
- The repo is public, so CI minutes are free.

---

## Part 2 — Configuration instead of code

### 2.1 Where configuration lives

| File | Tracked? | Holds |
|---|---|---|
| `data/profile.yaml` | **no longer tracked** (gitignored) | facts and the writing brief |
| `data/profile.private.yaml` | gitignored (unchanged) | phone, address, GPA, budget, notify, **search criteria and tracks** |
| `data/employers.yaml` | gitignored (unchanged) | the employer registry |
| `data/context/*` | gitignored (unchanged) | long-form source material |
| `data/profile.example.yaml` | tracked, new | a neutral, fictional example of every key |
| `data/alerts.json` | **no longer tracked** | the IMAP/export drop file (it holds the owner's mail) |

The owner's files stay on disk exactly where they are. `git rm --cached` removes
them from tracking only. `apply init` copies the example when no profile exists.

### 2.2 Tracks become data

Today `Track` is a closed enum of four finance tracks. It becomes a registry
loaded from `search.tracks` in the profile:

```yaml
search:
  default_track: corporate          # what a posting with no keyword hits becomes
  tracks:
    quant:
      keywords: {"market making": 5, "quantitative": 4, ...}
      resume: projects_first        # or experience_first
      code_link: true               # letter may offer a link to the proof project
    banking: {...}
```

- **Defaults:** when `search.tracks` is absent, the registry is today's four
  tracks with today's keyword weights, so the owner's setup is unaffected.
- **Code impact:**
  - `Track` becomes a validated string. `Track.parse` checks it against the
    registry.
  - The ~14 call sites in `classify`, `generate`, `writer`, `cli` and `web`
    switch from enum members to strings.
  - The DB already stores plain strings.
- **Letter templates:** `templates/letters/<track>.tex.j2` is used when it
  exists. Otherwise a new `generic.tex.j2` is used, which honours `code_link`.
  The owner's four templates keep working.
- **Resume templates:** chosen by the track's `resume:` layout.
  `projects_first` maps to today's `resume_quant`; `experience_first` maps to
  `resume_traditional`. Today's mapping is preserved by the defaults.
- **Profile references:** `projects[*].tracks` and
  `writing.letter.proof_asset.<track>` already key by string, so they need no
  change.

### 2.3 The scorer reads criteria from config

Every list in `score.py` gets a config key. The current lists become the
defaults, so the owner's behaviour is unchanged. Phrases in config are plain
text matched on word boundaries with flexible whitespace. A phrase starting
with `re:` is a raw regex, for the rare case that needs one.

```yaml
search:
  thresholds: {pursue: 70, maybe: 45}
  locations:                        # first match wins, in order
    - {label: "New York", weight: 25, match: ["new york", "nyc", "manhattan", "hudson yards", "re:\\bny\\b"]}
    - {label: "local to Richmond", weight: 15, match: ["richmond", "virginia", ...]}
    - {label: "remote", weight: 10, match: ["remote", "work from home"]}
    - {label: "US hub", weight: 6, match: ["boston", "chicago", ...]}
  us_only: true                     # false turns off the outside-the-US reject
  roles:   [{match: "quantitative research", weight: 25}, ...]
  timing:  [{match: "summer 2027", weight: 18}, ...]
  title_timing: [{match: "2027", weight: 14}]
  reject:
    seniority: ["senior", "director", ...]      # [] for an experienced hire
    functions: ["sales", "recruiter", ...]
    technical: ["software engineer", ...]       # [] for a software engineer
    max_years_experience: 3                     # null disables
    advanced_degree_required: true              # reject postings that require one
```

- **Rejection labels** (`seniority`, `function`, `technical`, ...) are kept, so
  `--show-rejects` output and the existing tests still read the same.
- **Locations:** the hardcoded "New York +25 / Richmond +15 / remote +10 /
  hub +6" ladder becomes the ordered `locations` list. The reason string uses
  each entry's `label`.
- **Class standing:** derived from the graduation date as now. It only gates
  the class-year rejects, and only when an education entry is `current`.
- **Example scope:** `parse.py` and `classify.py` heuristics (deadline parsing,
  role-word lists) are out of scope. They are field-neutral enough, and the
  wizard's role phrases cover scoring.

### 2.4 De-personalise the code

These go:

- `ajaiupadhyaya` in the ATS User-Agent (made generic).
- The `apply context pull` help example (`owner/repo`).
- The PDF-filename docstring.
- `resolve.py`'s hardcoded Workday search terms: they now come from the
  wizard's role phrases, with today's values as the default.

A test asserts that the exported tree contains none of a deny-list of owner
strings: name, emails, GitHub handle, school.

---

## Part 3 — `apply setup`, the onboarding wizard

A terminal flow built on the `rich` and `typer` tooling the CLI already uses.
It can be resumed: each step records its completion in
`data/.setup_state.json` (gitignored), and `apply setup --step <name>` re-runs
one step. It never overwrites an existing file without showing a diff and
asking. Replaced files are backed up to `data/.backup/<timestamp>/`.

### Steps

1. **Toolchain check.** Python, uv, pdflatex, MiKTeX auto-install. Each missing
   piece prints its exact install command. Setup continues, and generation
   stays unavailable until TeX exists.

2. **API key.** Ask with `getpass`, store with `host.set_secret`, then verify
   with one minimal request (a one-token Haiku message, under $0.001, recorded
   in the ledger). Ask for the budget ceilings, defaulting to today's
   $15 / $2 / $0.50.

3. **Documents.**
   - Inputs: a resume path (`.pdf`, `.docx`, `.txt`, `.md`), then optionally
     one or more cover letters and other writing (portfolio pieces, project
     write-ups).
   - Text extraction: `.pdf` through `pypdf` (already a dependency); `.docx`
     through the standard library (`zipfile`, reading `word/document.xml`).
   - The extracted text is shown back so he can see it parsed.
   - Each source is copied as text into `data/context/` with a header naming
     the file it came from. Context files are what the letter writer and the
     auditor may cite, so this keeps letters grounded in his own documents.

4. **The blurb.** Short questions, each optional except the first:
   - What kind of roles? (free text)
   - Internship, full-time, or both?
   - Where? (ranked, plus remote OK yes/no)
   - Firms you most want (names)
   - Firms or kinds of work to avoid
   - Links (LinkedIn, GitHub, portfolio)
   - Anything else a letter should know about you

   **Asked directly and never inferred**, because a letter states them as fact
   and a wrong one is the worst error the writer can make:
   - work authorization
   - sponsorship now / in future
   - graduation date or "not a student"
   - availability

5. **Draft.**
   - One API request (Opus, structured JSON output, about $0.30–0.60) turns the
     documents and the blurb into proposals for:
     - `profile.yaml`: identity, education, experience, projects with
       per-track tags, skills, links, essays left null, and a `writing:` brief
       in the same instruction-not-prose style as today.
     - `search`: tracks with keywords and resume layout, roles, timing,
       locations, rejects and thresholds.
     - A list of employer names and aliases.
   - The request goes through `llm.call` and the budget ledger like every other
     call.

6. **Ground the draft.** Deterministic, before he sees it:
   - Every digit-bearing token in the drafted profile must appear in his
     documents or blurb (the same `_digit_tokens` rule `generate.lint` uses).
     Any that don't are replaced with `ASK`.
   - The authorization fields are overwritten with his direct answers, whatever
     the model said.
   - Experience entries whose organisation name does not appear in his
     documents are dropped and listed.

7. **Review.**
   - Each section is shown as YAML and he picks **accept**, **edit**
     (opens `$EDITOR`, or Notepad on Windows), or **redo with a note**, which
     re-runs that section's request with his correction.
   - Nothing is written until he accepts.
   - The wizard writes `profile.yaml`, the private overlay and the context
     files.

8. **Employers.** For each named firm, find its board without guessing:
   1. Try slug candidates derived from the name against the Greenhouse, Lever
      and Ashby public APIs. An HTTP 200 with jobs counts as verified.
   2. Otherwise ask for the careers-page URL and run the existing
      `resolve.find`.
   3. Otherwise list the firm as unresolved, with the README instructions.

   Verified entries are written to `employers.yaml` with the role phrases as
   Workday search terms. The model never supplies a slug, and nothing
   unverified is written.

   Outbound note: the slug probe reaches the same hosts `apply.sources.ats`
   already declares. It lives in `resolve.py`, which is already allowed `*`, so
   `outbound.py` does not change.

9. **Optional extras**, each skippable:
   - Gmail alert ingestion: IMAP user and app password, the password going to
     the OS store. `imap.user` becomes a profile key instead of assuming
     `identity.email`, which may be a school address.
   - ntfy topic.
   - The daily schedule (`apply schedule --install`).

10. **Finish.**
    - Run `apply doctor`, then `apply discover --dry-run`, and show the top
      results so he sees it working on his criteria.
    - Print the five commands he'll actually use.
    - Remind him that APPLY never submits.

### Guarantees the wizard keeps

- Nothing it writes can promote an application or submit anything. It touches
  config files only.
- It never puts a fact into `profile.yaml` that isn't in his documents or his
  answers, which is the grounding rule applied to configuration.
- It never asks for SSN, DOB or bank details, and refuses to store them if
  pasted. A free-text field matching an SSN or DOB pattern is rejected with a
  message.

### Module layout

- `src/apply/setup/__init__.py`: the step runner and state file.
- `src/apply/setup/extract.py`: pdf, docx and txt to text.
- `src/apply/setup/draft.py`: the prompt, the JSON schema and the grounding
  pass.
- `src/apply/setup/employers.py`: slug probing, plus `resolve` glue.
- `src/apply/host.py`: from Part 1.

---

## Part 4 — The friend's repo and docs

### 4.1 Export

`scripts/export_starter.py` builds the starter repo:

1. Copies `git ls-files` output from `main` into a target directory.
2. Runs the owner-string deny-list check.
3. Writes a fresh single commit.

Publishing it as a new GitHub repo is a separate step the owner confirms
(the suggested name is `apply-starter`, private, with the friend invited).
Later updates are re-exported with the same script, and the friend pulls them.
The friend's own data is gitignored, so pulls never conflict with it.

### 4.2 Docs

- **README:** a "Start here" section per OS at the top (`install.ps1` /
  `install.sh`, then `apply setup`). The Mac-only phrasing ("launchd",
  "Keychain", "zsh") is moved under per-OS headings. The "What it will not do"
  table is kept as is.
- **`AGENTS.md`:** new. Cursor reads it. It holds the `CLAUDE.md` rules, plus
  "if the user hasn't run `apply setup`, tell them to run it" and "use `uv`".
- **`CLAUDE.md`:** gains one line pointing at `host.py` for OS-specific code.

---

## Testing

All tests use FakeClaude. No test calls the API (existing rule).

- **Host layer:** each function with `sys.platform` monkeypatched; subprocess
  and `os.startfile` stubbed.
- **Schedule:** the Windows task XML is rendered and asserted on (trigger time,
  `StartWhenAvailable`, working directory). `schtasks` is stubbed.
- **Encoding:** a grep test for `read_text(`, `write_text(` and `open(` without
  `encoding=` in `src/`.
- **Config-driven scorer:**
  - Existing `test_score.py` passes unmodified, which proves the defaults.
  - New tests use a non-finance config, such as a software engineering intern
    in Seattle, and assert that SWE roles pursue and finance roles don't.
  - The golden corpus check runs locally for the owner.
- **Tracks:** a custom track resolves to `generic.tex.j2` and the chosen resume
  layout. The PDF test compiles it.
- **Wizard:**
  - Extraction from a fixture `.docx` and `.pdf`.
  - The grounding pass drops an invented number and an invented employer, and
    overrides authorization.
  - A full scripted run, with stdin answers and FakeClaude returning a canned
    draft, writes the expected files and nothing else.
  - The SSN pattern is refused.
- **Export:** the deny-list test runs on the exported tree.
- **CI:** the Windows and macOS matrix from 1.7.

## Risks

- **MiKTeX first compile.** On-the-fly installs can be slow or blocked by a
  proxy. Mitigation: `install.ps1` pre-installs the package list with `mpm`.
- **Draft quality varies with how messy the resume is.** Mitigation: the review
  step, plus `--step draft` to redo it. Grounding means a bad draft is
  incomplete, not wrong.
- **Slug probing misses firms on unsupported ATSes** (iCIMS, Taleo). This is
  expected and reported honestly. He can still use `apply add` and the alert
  mail for those.
- **The owner's public history still holds the old profile.** Scrubbing history
  is out of scope, so the owner should decide separately whether to make this
  repo private.

---

## Addendum (2026-10-08): rebased onto `publish-clean`

The owner chose to build on the existing `publish-clean` branch rather than
`main`. That branch already does much of Part 2:
- `data/profile.yaml` is gitignored, and a fictional persona (Rae Mercer) is
  both the scaffold and the test fixture.
- The gate's vocabulary is YAML: `src/apply/search.defaults.yaml`, overridden
  per top-level block by a gitignored `data/search.yaml`.
- There is a 9-question `apply setup` with `--persona`/`--non-interactive`,
  and launchd/systemd/cron backends.
- `secrets.lookup` reads the environment, then the Keychain, then `keyring`.
- CI runs on Ubuntu and macOS, and there are owner-string tests.

Where this spec and the branch differ, the branch's shapes win:

- **2.1 / 2.3:** search criteria stay in `data/search.yaml` with the branch's
  keys (`rejects`, `class_scoped`, `geography`, `non_us`, `country`,
  `role_fit`, `timing`, `title_timing`, `thresholds`), not in
  `profile.private.yaml`. They gain two blocks:
  - `tracks:` replaces the spec's `search.tracks`.
  - `limits:` holds max years of experience, the advanced-degree reject and
    the graduate-programme reject.
- **1.1:** OS-specific code stays in the seams the branch already has
  (`secrets.py`, `schedule.py`, `cli.read_clipboard`, `notify.banner`,
  `generate.tex_hint`), each gaining a Windows branch. A small `host.py` holds
  only `open_path`, which `cli` and `web` share.
- **1.2:** `keyring` becomes a real dependency, with a new
  `secrets.store(name, value)` written through `keyring` (service `"apply"`,
  username = secret name, the layout `lookup` already reads). CLAUDE.md's
  "nothing writes a credential" becomes "nothing writes a credential to a
  file".
- **1.3:** the launchd label is already neutral (`apply.daily`, legacy label
  retired). Windows gets a fourth backend, `TaskSchedulerBackend`.
- **1.7:** the CI file is `.github/workflows/tests.yml`. Windows joins both of
  its jobs.
- **Part 3:**
  - `src/apply/setup.py` becomes the package `src/apply/setup/`. Its existing
    contents move unchanged into `__init__.py`.
  - The new wizard is the interactive default.
  - The old nine questions remain as `apply setup --quick`, for someone
    without an API key.
  - `--persona` and `--non-interactive` are unchanged, since CI's smoke job
    uses them.
  - Key verification is `llm.ping()`, a free `models.list` request, in place
    of a Haiku call.
  - The draft uses `llm.DEFAULT_MODEL` (Sonnet 5.5 on this branch), with a
    per-call cap of at least $2 for the `setup` purpose.
  - Graduation date stays required: the wizard asks "expected, or when you
    graduated", so a non-student still has one.
- **4.1:** the export keeps authorship lines (LICENSE, the repository URL, the
  legacy launchd label). The deny-list targets the owner's biography, using
  the branch's `AUTHORS_BIOGRAPHY`, not the owner's name as author.
