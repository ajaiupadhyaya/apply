# APPLY

Everything up to the submit button.

Paste a job description, get back a tailored cover letter, the right resume
variant, a filled field pack for the portal, and a tracked record with a
deadline. Then read it yourself and submit it yourself.

```
apply discover                 # poll every target firm; file what is worth reading
apply gen <slug>               # letter + resume + field pack
apply review <slug>            # you read it; this is the gate
apply submit <slug>            # you submitted it; this records that
apply serve                    # the dashboard, localhost:8787
```

`apply add --clipboard` still takes a pasted posting, and always will — it is the
only way Handshake-hosted listings get in.

---

## What it will not do

These are enforced in code, not just documented.

| Never | Where it is enforced |
|---|---|
| Submit an application | Nothing in `src/` can make an outbound write. There is no HTTP POST, no browser driver, no scheduler. A test greps for them. |
| Scrape or log into Handshake | `apply add --url` rejects `*.joinhandshake.com` with a message telling you to paste instead. The userscript excludes the domain. |
| Store credentials, SSN, DOB, or bank details | They are not in `profile.yaml`, so they cannot reach a document or a field pack. The API key is read from the environment and never written. |
| Promote an application without a human | `ready` accepts only the `review` action; `submitted` accepts only the `submit` action. Every other caller is refused by `db.transition`. |
| Put a fact in a letter that is not in `profile.yaml` | The lint fails the build on any number or date sourced from neither the profile nor the posting. |

---

## Setup

Needs Python 3.11+, [uv](https://docs.astral.sh/uv/), and a TeX install.

```bash
uv sync                                        # or: uv sync --all-extras, for the API path
brew install --cask mactex-no-gui              # if pdflatex is missing
uv run apply init
uv run apply doctor                            # what is still missing
```

Then fill in the two files that hold your facts:

```bash
cp data/profile.private.example.yaml data/profile.private.yaml
$EDITOR data/profile.private.yaml              # phone, address, GPA. gitignored.
$EDITOR data/profile.yaml                      # everything else
```

`apply doctor` lists every value still marked `ASK`. Generation refuses to render
one into a document, so the list is the to-do list.

Seed the pipeline with two real-shaped postings:

```bash
uv run apply seed
```

---

## How the letters get written

**Claude writes every letter and portal answer. Nothing is pasted from a
template.** A second, independent request audits each draft before a PDF exists.

```
apply gen <slug>                    # Claude writes, lints, fits, audits, revises
apply gen <slug> --from-body        # check and render your own edits to body.md
apply check <slug>                  # audit the current letter again, change nothing
apply gen <slug> --llm manual       # write PROMPT.md to paste into Claude by hand
```

What Claude reads, all of it yours:

- **`data/profile.yaml`** — the facts (education, experience, projects, skills,
  work authorization, availability) and a **writing brief** under `writing:`:
  instructions about voice, structure and emphasis, never sentences. Edit the
  brief and every future letter changes.
- **`data/context/`** — longer source material. `apply context pull owner/repo`
  files a GitHub README in your own words (introduction, every heading, each
  section's opening). Everything here is something a letter may claim, so curate
  it like a reference list.
- **the posting**, verbatim.

Phone, street address and GPA are never sent to the API.

### The loop

```
write    one request drafts the letter and both portal answers
lint     free — banned phrases, unsourced figures, sponsorship wording
fit      free — typeset it; it must be one page
audit    paid — a separate request checks every sentence against your sources
revise   paid — the writer gets its draft back with the exact problems
```

Free checks run first, so nobody pays to audit a draft that runs to two pages.
Up to three drafts. If an **unsupported claim**, a **wrong authorization
statement**, or a **blocking** finding survives the last one, no PDF is built —
the draft stays in `body.md` for you to fix by hand. Style findings never block:
"correct" is the auditor's job and "good" is yours, so they are recorded and
shown at review time instead.

Your own edits to `body.md` are audited but never rewritten.

The first live run caught exactly the failure this exists for: the writer kept
inventing "starting in May" because the brief asked for availability and the
profile held none. The auditor refused it three drafts running. That is why
`availability:` now exists in the profile, and why the writer is told explicitly
to state no start date while it is empty.

### What it costs

Measured on Opus 5 at high effort: **about $0.42 for a letter verified on the
first draft**, most of it the model's reasoning, which bills as output. A draft
needing revisions costs more — the refused run above was $0.81 for three. At the
default $15/month ceiling that is roughly 30–35 letters. `--effort medium` cuts
the reasoning roughly in half; whether that is worth it is your call.

The shared source block is cached, so an audit or a revision re-reads your
profile and context at about a tenth of the price.

### The lint

Runs on the prose before it becomes a PDF, on every draft and every answer.

- The banned words: *passionate, dynamic, synergy, leverage my skills,
  fast-paced environment, I believe I would be a great fit*
- Any superlative about the firm the posting did not use first
- Any figure in neither your profile, your context documents, nor the posting
- Any sentence about sponsorship that contradicts your profile
- More than one page after compilation

---

## Finding the postings

`apply discover` polls every firm in the employer registry and files anything
worth reading. It calls no model and writes no document, so it costs nothing and
can run as often as you like.

```
apply targets                  # who gets polled, and how
apply discover --dry-run       # score everything, write nothing
apply discover --show-rejects  # and explain what was dropped
```

Sources are public job-board APIs, not scrapers:

| ATS | Endpoint | Notes |
|---|---|---|
| Greenhouse | `boards-api.greenhouse.io` | one request per firm, descriptions included |
| Lever | `api.lever.co/v0/postings` | one request per firm |
| Ashby | `api.ashbyhq.com/posting-api` | one request per firm |
| Workday | the `/wday/cxs/` endpoint its own careers page calls | two steps: list, then one request per posting |

Measured on 2026-09-20: Jane Street returned 228 postings through Greenhouse,
BlackRock 50 analyst hits through Workday. Greenhouse leaves
`application_deadline` empty almost always; Workday carries a real deadline in
`endDate`, which appears after hydration.

Each firm is configured once, by hand, in `data/employers.yaml` — the slug or the
Workday tenant and site. `data/employers.example.yaml` explains where to find
them. That file is gitignored: the list of firms you are targeting is strategy,
not code.

### The gate

A Workday employer will return four hundred openings, of which perhaps three are
plausible. Paying a model to read the other three hundred and ninety-seven is how
a twenty-dollar balance disappears in a week, so `score.py` runs first and runs
free:

```
fetch     one request per employer
dedupe    by fingerprint, across sources and against what is already stored
score     free, on titles and locations
hydrate   one request per posting — only for the ones still standing
re-score  now with the body, where the disqualifiers live
record    pursue and maybe become postings; reject never does
```

Hard rejects, each of which names itself: senior titles, engineering roles,
off-function roles, anything outside the US, three or more years of required
experience, a required advanced degree. Positive weight goes to role fit, timing
(summer 2027, campus, new grad, pre-doc), the employer's priority, and above all
**New York**, which is the single heaviest signal in the model.

Verdicts: `pursue` (≥70, worth a letter), `maybe` (45–69, filed and shown to
you), `reject` (dropped, with a reason).

On a live four-employer pass: 555 fetched, 497 unique, 447 rejected for free.

### Handshake

`apply ingest` reads the job-alert mail Handshake already sends you and files
the postings out of it. APPLY never logs into Handshake and never fetches a page from it. Handshake
emails you job matches, and reading your own inbox is not automated access — so
the route in is saved-search alerts funnelled into one Gmail label.

```
apply ingest --imap            # read the mailbox directly; what an unattended run uses
apply ingest --file x.json     # read an export, when Claude does the fetching
```

Two transports, one parser. `--imap` needs a Gmail app password and runs from
cron; `--file` takes an export and is the fallback when a Workspace forbids app
passwords. The parsing is the part that is hard, and it is shared.

An alert carries a title, an employer, a location and sometimes a deadline — but
never a description. So nothing from this channel can reach `pursue` on the
strength of a title, by construction: it is filed for you to open, not fed to a
letter writer. That is the deliberate cost of not scraping.

**[docs/handshake-alerts.md](docs/handshake-alerts.md)** covers which saved
searches to create. Ignore its Gmail-filter section — the ingester queries the
mailbox directly and needs no labels.

### LinkedIn

The same pipeline reads LinkedIn's job-alert mail. **[docs/linkedin-alerts.md](docs/linkedin-alerts.md)**
has the nine saved searches to create and the one setting to switch on.

Alert postings arrive as titles only. Target firms are recognised under
LinkedIn's spellings and collapse with the copy from the firm's own board; firms
you haven't registered are listed after each ingest with the command to add
them; re-posts ("Jobs via eFinancialCareers") are flagged; and every link is
stripped of LinkedIn's one-time sign-in token before anything is stored.

```
apply describe <slug> --clipboard   # attach the full posting to a title-only one
```

It appends the text, reads the deadline and pay out of it, and re-scores the
posting against the full description — which is where the disqualifiers live.

---

## Running it while you are away

`apply run` is one unattended pass: discover, ingest the alert mail, write
documents for what earned one, report. It is what the scheduled job runs.

```
apply run --dry-run            # score everything, write nothing
apply run                      # the real pass, free (deterministic letters)
apply run --llm api --notify   # Claude writes them; notify when something needs you
apply runs                     # what the scheduled passes have done
```

What it will never do, whoever calls it:

- move an application past `generated` — `ready` and `submitted` belong to the
  review and submit actions, and this code path does not call them
- regenerate something that already has documents, so running it twice costs
  nothing the second time
- spend past the ledger's ceilings; a refused call ends that step, not the run
- do anything at all if `data/HALT` exists

One employer being down, one letter failing to compile, or the mailbox being
unreachable are recorded and stepped over. A run that half-worked beats a run
that raised.

### On a schedule

```
apply schedule --show                    # print the LaunchAgent, install nothing
apply schedule --install --at 06:30
apply schedule                           # what is currently scheduled
apply schedule --remove
touch data/HALT                          # pause tonight without uninstalling
```

launchd rather than cron: it survives reboots, needs no terminal open, and
catches up a missed run after the laptop wakes. The job runs through `zsh -lc`
so `~/.zshrc` is sourced and the Keychain-held API key is actually present —
a bare invocation would silently fall back to the free path.

### Notifications

A quiet run notifies nothing. A system that pings every morning to say it found
nothing gets muted within a fortnight, and then the one morning it matters the
notification is invisible too. It interrupts only when something is ready, needs
reading, closes within seven days, or broke.

`out/LATEST_RUN.md` is always written either way. Set `notify.ntfy_topic` in
`profile.private.yaml` to get a push on your phone as well.

---

## What it costs to run

The discovery pass is free. Letter writing and verification are not, so
`budget.py` keeps a ledger and three ceilings — per call, per run, per month —
checked before every request and recorded after every one. When a ceiling would
be crossed the call does not happen, and the run continues without that step.
Running out of money should look like a smaller overnight run, not a broken
system.

```
apply spend                    # month to date, by purpose
apply spend --ledger           # every individual call
```

Defaults are $0.50 per call, $2.00 per run, $15.00 per month — deliberately under
the $20 of credits, so a runaway month cannot eat the balance before you notice.
Change them under `budget:` in `profile.private.yaml`.

Rough costs: a letter on Opus 5 runs $0.10–0.20 because thinking bills as output;
a verification pass is $0.05–0.10. Discovery and scoring are $0.00.

---

## The state machine

```
draft ──generate──> generated ──YOU read it──> ready ──YOU submit it──> submitted
                         │                        │
                         └────── regenerate ──────┘
submitted ──> acknowledged ──> assessment ──> interviewing ──> offer
                                                          └──> rejected
any ──> withdrawn
```

Regenerating a `ready` application returns it to `generated` and clears
`reviewed_at`. A re-write requires a re-read. Every transition writes an `event`
row, so the log is an audit trail rather than a summary.

`apply submit` records that **you** submitted the application in the employer's
portal. It does not contact the employer.

---

## The dashboard

`apply serve` → http://localhost:8787

The table is sorted by deadline and drawn as a time axis: one hairline down the
left gutter, one tick per posting, an accent tick inside seven days, and a hollow
ring below the measure for a posting whose deadline is unknown. `ready` is the
only state that needs your hands, so it is the only thing on the page with
colour.

The detail page carries the posting verbatim, an inline PDF preview, and the
field pack as a column of copy buttons in roughly the order Workday and
Greenhouse ask for things. That last part is the least glamorous feature here
and it saves the most time.

---

## Commands

| | |
|---|---|
| `apply init` | create `apply.db`, scaffold the profile |
| `apply discover [--dry-run] [--hydrate N] [--show-rejects]` | poll every target firm and file what is worth reading |
| `apply ingest [--imap\|--file F]` | file the postings out of Handshake and LinkedIn alert mail |
| `apply describe <slug> --clipboard` | attach the full posting to a title-only one, and re-score it |
| `apply resolve <careers-url> --name N` | work out a firm's job board and print its registry entry |
| `apply targets` | the employer registry |
| `apply run [--llm api] [--notify]` | one unattended pass: discover, ingest, write, report |
| `apply schedule [--show\|--install\|--remove] [--at HH:MM]` | run the pass every morning via launchd |
| `apply runs` | what the scheduled passes have done |
| `apply spend [--ledger]` | model spending against the monthly cap |
| `apply doctor` | unresolved profile values, toolchain, credential |
| `apply add --clipboard\|--file\|--stdin\|--url` | add a posting |
| `apply gen <slug> [--track T] [--llm api] [--from-body] [--anchor "…"]` | build the documents |
| `apply check <slug>` | audit the current letter again, without rewriting it |
| `apply context [pull owner/repo]` | the source material Claude reads |
| `apply show <slug> [--jd]` | everything known about one posting |
| `apply review <slug>` | opens the PDF, asks, promotes `generated → ready` |
| `apply submit <slug>` | asks, promotes `ready → submitted`, queues a follow-up |
| `apply mark <slug> <status>` | ack, assessment, interviewing, offer, rejected, withdrawn |
| `apply status [--all]` | the pipeline |
| `apply digest [--days N]` | deadlines, follow-ups, stale drafts |
| `apply fields <slug> [--plain]` | the field pack, for copying |
| `apply followup <slug> "<action>" [--in N]` | queue a follow-up |
| `apply open <slug>` | open `out/<slug>/` |
| `apply serve` | the dashboard |
| `apply rm <slug>` | delete the record (files are kept) |

---

## Layout

```
data/profile.yaml            every fact and every letter sentence. Tracked.
data/profile.private.yaml    phone, address, GPA, targets, budget. Gitignored.
data/employers.yaml          which firms to poll, and how. Gitignored.
data/employers.example.yaml  the schema, and where to find each slug.
data/apply.db                SQLite. Gitignored.
templates/letters/*.tex.j2   one per track, extending base.tex.j2
templates/resumes/*.tex.j2   quant and traditional
templates/web/               the dashboard
src/apply/                   models, db, profile, parse, classify, generate,
                             fieldpack, digest, llm, cli, web
src/apply/sources/           greenhouse, lever, ashby, workday adapters
src/apply/sources/alerts.py  job-alert email parsing
src/apply/resolve.py         find a firm's board from its careers page
src/apply/score.py           the free relevance gate
src/apply/discover.py        one unattended pass
src/apply/budget.py          the spend ledger and its ceilings
src/apply/run.py             one unattended pass
src/apply/notify.py          summary file, macOS banner, optional phone push
src/apply/schedule.py        the launchd agent
src/apply/outbound.py        every host this system may reach, and why
docs/handshake-alerts.md     Handshake setup
docs/linkedin-alerts.md      LinkedIn setup: the nine searches and one setting
out/<slug>/                  generated artifacts. Gitignored.
tools/autofill.user.js       optional Tampermonkey script. Fills; never clicks.
```

---

## Deliberate deviations from the spec

1. **Claude writes the letters; there is no template prose.** The original spec
   composed letters from sentences stored in the profile. They read as
   templates, so they are gone: the profile now holds a writing brief of
   instructions, and an independent audit plus the deterministic lint are what
   make a model-written letter safe to send.

2. **Resume templates are `.tex.j2`, not `.tex`.** A static `.tex` would have to
   embed phone, address, and GPA, which live in the gitignored overlay.
   Rendering them keeps private facts out of version control.

3. **The hallucination guard allows numbers from the posting, not only the
   profile.** A figure quoted from the job description is sourced, not invented,
   and paragraph 4 often needs one. The guard is still absolute: a number from
   neither source fails the build.

4. **No HTMX.** A CDN script tag would break the offline-forever premise, and
   vendoring an unverifiable blob is worse. State changes are form POSTs with a
   redirect; the only scripted interaction is the copy button. At this scale a
   client framework buys nothing.

Plus one addition: `apply digest` lists deadlines past the 14-day horizon under
*Further out*, quietly. Not urgent should not mean invisible.

---

## Tests

```bash
uv run pytest -q
```

`tests/test_acceptance.py` is the definition of done — the twelve checks from the
handoff spec, named after the behaviour each protects. The PDF tests skip
themselves when `pdflatex` is absent.

The seed fixtures in `tests/fixtures/` are **representative text, not the live
postings.** Verify against the real listing before you apply to anything.
