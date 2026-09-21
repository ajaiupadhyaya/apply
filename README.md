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

## The four-paragraph letter

Structure is fixed, because it is what makes the letters consistently good:

1. **Position and timing.** Which role, that you graduate May 2027, one clause of
   why this firm. Two sentences.
2. **The proof paragraph.** *One* asset, in operational detail. This is the
   paragraph that gets the letter read. The track picks the asset:
   `quant` → OhCamel · `allocator` → the Bloomberg/WRDS consulting work ·
   `banking` → that plus BASIS · `corporate` → that, framed as reporting.
3. **Supporting evidence.** Two other items, one sentence each.
4. **Why this firm.** Cites something specific and checkable from the posting —
   a platform, a mandate, a team. Never generic praise.

All of that prose lives in `data/profile.yaml` under `letters:`, not in code, so
you can rewrite the voice of every letter without touching `src/`.

### The lint

Runs on the prose, before it becomes a PDF. A letter that fails produces **no
PDF**, and deletes any stale one, so yesterday's letter can never look current.

- The banned words: *passionate, dynamic, synergy, leverage my skills,
  fast-paced environment, I believe I would be a great fit*
- Any superlative about the firm the posting did not use first
- Any number or date that appears in neither `profile.yaml` nor the posting
- More than one page after compilation

### Writing the letter with Claude

Three ways, in increasing cost:

```bash
apply gen <slug>                    # deterministic draft. Free. Always works.
                                    #   ...also writes out/<slug>/PROMPT.md
apply gen <slug> --from-body        # render the paragraphs you saved to body.md
apply gen <slug> --llm=api          # Claude writes it. ~$0.10–0.20 a letter.
apply check <slug>                  # Claude reads it back against the posting
```

The deterministic draft is factually safe but flat — it is a floor, not a
ceiling. `PROMPT.md` contains the posting, the profile slice this track is
allowed to cite, the structure, and the banned list; paste it into Claude, save
the four paragraphs to `out/<slug>/body.md`, and render with `--from-body`.

For `--llm=api`, export a key from your Anthropic Console:

```bash
export ANTHROPIC_API_KEY='sk-ant-...'          # put this in ~/.zshrc
```

Nothing is written to disk and nothing is stored in `apply.db`. Whatever the
model returns goes through the same lint as the deterministic draft — it cannot
introduce a number that is in neither the profile nor the posting, and it cannot
move an application one step along the state machine.

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
| `apply ingest [--imap\|--file F]` | file the postings out of Handshake's alert mail |
| `apply resolve <careers-url> --name N` | work out a firm's job board and print its registry entry |
| `apply targets` | the employer registry |
| `apply spend [--ledger]` | model spending against the monthly cap |
| `apply doctor` | unresolved profile values, toolchain, credential |
| `apply add --clipboard\|--file\|--stdin\|--url` | add a posting |
| `apply gen <slug> [--track T] [--llm api] [--from-body] [--anchor "…"]` | build the documents |
| `apply check <slug>` | have Claude read the letter against the posting |
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
docs/handshake-alerts.md     Handshake + Gmail setup
out/<slug>/                  generated artifacts. Gitignored.
tools/autofill.user.js       optional Tampermonkey script. Fills; never clicks.
```

---

## Three deliberate deviations from the spec

1. **Resume templates are `.tex.j2`, not `.tex`.** A static `.tex` would have to
   embed phone, address, and GPA, which live in the gitignored overlay.
   Rendering them keeps private facts out of version control.

2. **The hallucination guard allows numbers from the posting, not only the
   profile.** A figure quoted from the job description is sourced, not invented,
   and paragraph 4 often needs one. The guard is still absolute: a number from
   neither source fails the build.

3. **No HTMX.** A CDN script tag would break the offline-forever premise, and
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
