# APPLY

Everything up to the submit button.

APPLY watches the job boards of firms you name and the alert emails Handshake
and LinkedIn already send you. It throws away what doesn't fit, for free, and
says why. For what does fit, Claude writes a cover letter and the portal
answers from your own record, and a second, independent request audits every
claim against that record before a PDF exists. Then it stops. You read it, and
you submit it.

```
find     firms' own job boards, plus Handshake and LinkedIn alert mail    free
gate     seniority, geography, function, fit — every rejection says why   free
write    Claude drafts the letter and portal answers from your profile    ~$0.50
audit    a second request checks each claim against your sources
you      read it (apply review), then submit it yourself (apply submit)
```

It runs on your machine. The database is a SQLite file, the documents are PDFs
in a folder, and nothing about you leaves the laptop except the part of your
profile a letter is written from.

---

## What it will not do

Enforced in code and in tests, not just promised here.

| Never | How |
|---|---|
| Submit an application | Nothing transmits to an employer. Every module that sends a request is declared in `src/apply/outbound.py` with the reason its hosts are not employers, and the suite fails on an undeclared one. There is no browser driver in the codebase. |
| Scrape Handshake, LinkedIn or Indeed | Their postings arrive through the alert emails they already send you, or by paste. `apply add --url` refuses all three outright, subdomains included, and names the paste command instead. |
| Hold a credential in a file | The Anthropic key and the IMAP app password are looked up at call time — the environment, then the macOS Keychain, then a Secret Service keyring — and nothing here ever writes one. |
| Move an application without you | `ready` accepts only the `review` action and `submitted` only `submit`; every other caller is refused by `db.transition`. |
| Claim what you haven't done | The lint fails any figure written in digits that appears in neither your profile, your context documents nor the posting. Everything else rests on the audit, which is a model reading the draft against those same sources — a judgement, not a rule. Either failure means no PDF. One exception, in the table so you know about it: text you wrote yourself and pass back with `apply gen --from-body` is built on the lint alone when there is no key to audit it, and the letter is recorded `unverified`. |

---

## What it has done so far

`uv run python tools/numbers.py` reads the registry and the database and prints
the table below. This is one person's search, as of 2026-09-23. Run it against
your own pipeline and you get your own figures; nothing in this section is a
number anyone typed by hand.

| figure                | value |
|-----------------------|---|
| registry              | 152 firms — 75 workday, 64 greenhouse, 6 oracle, 3 ashby, 2 lever, 1 eightfold, 1 nextdata |
| gate                  | pursue ≥ 70, maybe ≥ 45 |
| vocabulary            | 87 reject patterns, 4 places, 49 non-US places, 35 role patterns, 15 timing patterns, 6 class-year patterns |
| postings filed        | 826 — 95 pursue, 535 maybe, 196 since screened out by a gate change |
| boards they came from | 319 oracle, 273 greenhouse, 195 workday, 19 nextdata, 8 eightfold, 5 lever, 4 alert, 3 ashby |
| last unattended pass  | 1232 fetched, 1022 rejected for free, 106 filed from boards, 4 from alert mail, 4 letters written |
| documents built       | 14 letters generated, 0 promoted past the human gate |
| model spend           | $6.04 over 41 calls for 12 letters — $0.50 a letter, audit included |

Four of those rows are the argument. **1232 fetched, 1022 rejected for free**
is the shape of the problem: one Workday employer alone can return four hundred
openings. The gate is regular expressions and arithmetic, it runs before any
model is called, and so none of those rejections cost anything.
**0 promoted past the human gate** is not an oversight — `ready` and
`submitted` are reached by a person typing `apply review` and `apply submit`,
and there is no other way in. The **196** rejects are postings filed under an
earlier version of the gate that `apply rescore` has since screened out; a
rejection is normally not stored at all. The **$0.50** is the whole cost of a
letter: the draft, the audit that checks it, and the revision the audit asked
for.

What this is not: it was built for one person's search, a 2027 finance hunt
centred on New York, and the shipped defaults are tuned for that search — which
titles are refused, which roles score, the graduating years it looks for.
`apply setup` writes the geography from the city you give it, but the rest is
still someone else's vocabulary until you edit it. It is a YAML file rather
than source code, `apply search` prints what is in force and where each block
came from, and [Make it yours](#make-it-yours) is how to change it. The registry
above is not shipped either: `data/employers.yaml` is one person's target list,
so it stays on their machine, and a clone starts with an example of the shape.

---

## Quick start

Needs Python 3.11+, [uv](https://docs.astral.sh/uv/), and TeX if you want PDFs.
Python 3.11 and 3.13 on Ubuntu and macOS are what the workflow in
`.github/workflows/tests.yml` covers.

**What a clone gets today.** This document describes the branch it is on, which
has not been merged. The default branch is an earlier version of this tool — no
`apply setup`, no `tools/numbers.py`, no frozen corpus, no CI workflow — so the
third line below is not a command there and the table above does not reproduce.
Once the branch is merged, a plain clone is what the quick start describes;
until then it is not, and that is the owner's merge to do, not yours.

```bash
git clone https://github.com/ajaiupadhyaya/apply && cd apply
uv sync
uv run apply setup --persona   # the example person, so there is something to read
uv run apply seed              # two invented postings, so there is a pipeline
uv run apply serve             # the dashboard, at localhost:8787
```

`--persona` writes the invented person this repository ships, Rae Mercer of
Example University, and gives you a profile complete enough to render a letter
and a resume end to end. When you want your own, `uv run apply setup --force`
asks nine questions — name, email, school, degree, graduation month, the city
you want to work in, the work you want, work authorization, a GitHub link — and
replaces the persona. It leaves everything it could not ask about marked `ASK`:
your experience and your projects, above all. `apply doctor` sorts those into
what blocks a command, what a document would print, and what nothing is waiting
on, and `apply gen` refuses to render a document that would carry the word
`ASK` to an employer.

Setup also writes `data/search.yaml` from the city you gave it, which is how
the gate learns where you want to work. It writes that file once and never
again: a second `apply setup` leaves it alone, `--force` included, because a
tuned search is work and `--force` is about the profile. So if you start from
the persona, the gate starts out looking for London, which is where she lives —
edit the city in `data/search.yaml`, or delete the file and run setup again.
`uv run apply search` prints what the gate is looking for and which file said so.

Finding and gating postings costs nothing and needs no key. Writing a letter
needs one, or needs you to write it yourself — see
[Without an API key](#without-an-api-key).

```bash
# macOS
security add-generic-password -U -a "$USER" -s ANTHROPIC_API_KEY -w
# Linux, if you have python-keyring installed and a Secret Service running
keyring set apply ANTHROPIC_API_KEY
# anywhere, in the shell that runs apply
export ANTHROPIC_API_KEY=...
```

`keyring` is not a dependency of this project — it is imported only if you
already have it — so on a headless Linux box the exported variable is the
ordinary route. A scheduled run does not inherit your shell's variables; see
[Running unattended](#running-unattended).

Typesetting needs `pdflatex` and the packages the templates load: geometry,
titlesec, enumitem, microtype, mathptmx, xcolor, hyperref, parskip and
`fontenc` with `T1`. `brew install --cask mactex-no-gui` on macOS; `apt install
texlive-latex-recommended texlive-latex-extra texlive-fonts-recommended` on
Debian or Ubuntu. Without TeX everything else still runs and no PDF is built.
`uv run apply doctor` says what is missing, at any point. To call `apply` from
any folder:

```bash
echo "alias apply='uv run --project $(pwd) apply'" >> ~/.zshrc   # or ~/.bashrc
```

---

## Make it yours

Nothing about your search is tracked by git. Every file below is gitignored.
`apply setup` writes `profile.yaml` from your answers and `search.yaml` from
the city among them, and copies the other two from the `*.example.yaml` that
ships beside each one.

| File | Holds |
|---|---|
| `data/profile.yaml` | your facts — education, experience, projects, skills, work authorization, availability — and a writing brief under `writing:` that sets voice, structure and emphasis. `data/profile.example.yaml` is a persona, Rae Mercer, who does not exist. |
| `data/profile.private.yaml` | phone, street address, GPA, budget ceilings, and a `search: thresholds:` block that overrides the gate's. Never sent to the API. |
| `data/employers.yaml` | which firms to poll, which board each uses, and any firm-specific rules. |
| `data/search.yaml` | the gate's vocabulary, as far as it is yours. Written once by setup, from the city you gave it; there is no `search.example.yaml`, because `apply search` prints the shipped blocks to copy. |

### The gate's vocabulary

The defaults live in `src/apply/search.defaults.yaml` and ship with the
package. `data/search.yaml` overrides them, one block at a time. A block
replaces the default whole rather than merging into it, because half a list of
rejects is harder to reason about than either the whole default or your own.

```yaml
# data/search.yaml — Berlin instead of New York.
#
# `geography` is replaced whole, so every place you still want a score for has
# to be here: `apply search` reports four places by default and two after this.
geography:
  primary: {weight: 25, label: Berlin, patterns: ['berlin']}
  remote:  {weight: 10, label: remote, match_title: true, patterns: ['remote']}

# Locations that disqualify. Named for the search it was written for; what it
# means is "somewhere I am not looking".
non_us: ['new\s+york', 'chicago', 'singapore']

# Adding a role pattern means restating the ones you are keeping. Copy the
# block out of src/apply/search.defaults.yaml and add your line to it.
role_fit:
  - ['climate\s+(research\w*|analyst)', 25]
  - ['quantitative[\s\w]{0,18}(research\w*|analyst|trader|trading)', 25]
  - ['graduate\s+(program|programme|scheme|analyst)', 23]
  # ... the other 32 pairs, or not, as you like
```

With that file in place, a Climate Research Analyst in Berlin scores 54 on
title alone and is filed; a Research Analyst in New York is rejected on
location. `uv run apply search` prints every block, how many entries it holds,
and whether it came from the defaults or from your file:

```
  block           entries    from
  thresholds            2    defaults
  rejects              87    defaults
  class_scoped          6    defaults
  geography             2    data/search.yaml
  non_us                3    data/search.yaml
  role_fit              3    data/search.yaml
  timing               15    defaults
  title_timing          2    defaults

places, first match wins: Berlin +25, remote +10
thresholds: pursue ≥ 70, maybe ≥ 45.
Override any block in data/search.yaml.
```

Thresholds move the same way: `thresholds: {pursue: 70, maybe: 45}`. They can
also be set under `search:` in `data/profile.private.yaml`, which is where the
shipped example puts them, and that copy wins — `apply search` prints the pair
in force and names the file it came from, because `pursue` is the bar an
unattended run spends money on. After any change, `uv run apply rescore
--dry-run` shows what the new vocabulary would do to the postings already
filed, and `apply rescore` applies it.

---

## Finding postings

`apply discover` polls every firm in `data/employers.yaml` through the public
API behind its careers page — Greenhouse, Lever, Ashby, Workday, Oracle
Recruiting Cloud, Eightfold, or the JSON a Next.js careers page embeds. It
calls no model, so it costs nothing. A firm behind bot protection is not
polled: getting past that would mean pretending to be a browser, which is the
line this project doesn't cross.

To register a firm, `apply resolve <careers page> --name "Firm"` reads the
page, works out which board is behind it, confirms the board answers, and
prints the block to paste into `data/employers.yaml`. `apply targets` lists
what is registered.

`apply ingest` reads Handshake and LinkedIn alert mail over IMAP or from an
export. Those postings carry a title and no description, so they are filed for
you to look at and never written up automatically; `apply describe <slug>`
attaches the full text once you have copied it. Which searches to save, and how
to get the mail somewhere APPLY can read it, are in
[docs/handshake-alerts.md](docs/handshake-alerts.md) and
[docs/linkedin-alerts.md](docs/linkedin-alerts.md).

`apply add` takes a posting by `--clipboard`, `--stdin`, `--file` or `--url`,
and refuses Handshake, LinkedIn and Indeed URLs outright.

Which board is which, what each endpoint costs, and how the paste routes behave
on a machine with no clipboard: [docs/finding-postings.md](docs/finding-postings.md).

---

## The gate

A Workday employer can return four hundred openings, of which perhaps three are
plausible. Paying a model to read the rest is how a small balance disappears in
a week, so the gate runs first, and free:

```
fetch     one request per employer
dedupe    by fingerprint, across sources and against what is already stored
score     titles and locations
hydrate   fetch the full description — only for postings still standing,
          best first, up to --hydrate (60); the rest wait for the next run
re-score  with the description, where the disqualifiers live
record    pursue and maybe are filed; reject never is
```

The hard rejects are regular expressions, not judgements. Most of them read the
title and nothing else, they match the words they were given and no synonyms,
and every one of them is a line in `src/apply/search.defaults.yaml` that
`data/search.yaml` can replace. Each names itself when it fires:

- **rank** (*title is senior*) — senior, sr., VP, director, principal, staff,
  lead, head of, chief, managing director, partner, manager, supervisor.
  "Rising Senior" and "senior year" are excluded, because they describe a
  student, not a job level.
- **off function** (*off-function*) — sales, but not "sales and trading";
  account executive, recruiting, talent, marketing, HR, facilities, events,
  coordinator, administrator, and about twenty more.
- **software and infrastructure titles**, which the reason line calls an
  engineering role: software engineer, SWE, backend, frontend, full stack,
  devops, SRE, security/infrastructure/platform/systems engineer, data
  engineer, ML engineer, developer, firmware, QA. Not every title with the word
  *Engineer* in it — the line these patterns draw is *building the product*, so
  "Privacy & Civil Liberties Engineer - New Grad" matches none of them, and one
  in New York came through the live pipeline as a `maybe`. If that is the wrong
  call for your search, the block to widen is `rejects.too_technical`.
- **somewhere you are not looking** (*outside the US*) — a location that
  matches no `geography` block and is on the `non_us` list. A location matching
  none and naming a region that is not a US state is refused too, but only
  while `country: us`: the fifty states are the one piece of geography the gate
  knows by heart rather than from your file. For a city outside the United
  States `apply setup` writes `country: elsewhere` and an empty `non_us`, so a
  search the shipped vocabulary has nothing true to say about refuses nothing
  for free.
- **out of reach on the description** — three or more years of required
  experience, a required advanced degree, or a title naming one ("Ph.D.
  Intern", "MBA Associate"; pre-doctoral roles pass). These need the full
  posting, so they run after hydrate.
- **a class year other than yours**, derived from your graduation date rather
  than stored, because a stored class year is wrong within a year.

A posting that states a graduation window ("expected graduation date of
December 2027 – June 2028") is rejected when your `grad_expected` falls outside
it. That is the real eligibility line for campus programmes: a May 2027
graduate is outside every 2027 summer analyst window and inside every 2027
full-time one. Only a window with a month on both ends counts; "the 2026–2027
academic year" and "June 2028 or earlier" are left for you to judge.

Some seniority is a firm's own vocabulary: at a bank "Associate" is the grade
above analyst, at a fund it is often the graduate hire. A registry entry's
`senior_grades: ["associate"]` rejects that word in that firm's titles only.

When the gate or the registry changes, `apply rescore` runs it again over the
discovered postings still in draft. One it now rejects leaves the pipeline but
stays in the database with its reason; postings you added by hand and anything
with a letter written are never touched.

Verdicts: `pursue` (70+, worth a letter), `maybe` (45–69, filed for you to look
at), `reject` (dropped, with the reason). The patterns and thresholds behind all
of this are configuration, not code: see [Make it yours](#make-it-yours).

---

## Writing

Claude writes every letter and portal answer. Nothing is pasted from a template.

What it reads, all of it yours:

- **`data/profile.yaml`** — the facts, and a writing brief under `writing:` that
  describes voice, structure and emphasis. The brief is instructions, never
  sentences, and editing it changes every future letter.
- **`data/context/`** — longer source material. `apply context pull owner/repo`
  files a GitHub README in the author's own words: the introduction, every
  heading, and each section's opening. Anything here is something a letter may
  claim, so curate it like a reference list.
- **the posting**, verbatim.

Phone, street address and GPA are never sent to the API.

### The loop

```
write    one request drafts the letter and both portal answers
lint     free: banned phrases, unsourced figures, sponsorship wording
fit      free: typeset it; it must be one page
audit    paid: a separate request checks every sentence against your sources
revise   paid: the writer gets its draft back with the exact problems
```

The free checks run first, so nothing is paid to audit a draft that runs to two
pages. There are up to three drafts. If an unsupported claim, a wrong
authorization statement or a blocking finding survives the last one, no PDF is
built, and the draft stays in `body.md` for you to fix. Style findings never
block. Being correct is the auditor's job and being good is yours, so style
findings are shown to you at review time instead.

Your own edits are audited, when there is a key to audit with, but never
rewritten:

```
apply gen <slug>                  # write, check, audit, revise
apply gen <slug> --from-body      # check and render your edits to body.md
apply check <slug>                # audit again, change nothing
apply gen <slug> --llm manual     # write PROMPT.md to paste into Claude by hand
```

With no key, that second line is still the way to a PDF — see
[Without an API key](#without-an-api-key).

The first live run showed why the audit exists. The brief asked the closing to
state availability, and the profile held none, so the writer kept inventing a
start date. The audit refused it three drafts running, which is why
`availability:` is now a profile field, and why the writer is told explicitly to
give no start date while it is empty.

### The lint

It runs on every draft and every portal answer, before anything is typeset.

- the banned phrases: *passionate, dynamic, synergy, leverage my skills,
  fast-paced environment, I believe I would be a great fit*
- a superlative about the firm that the posting didn't use first
- a figure written in digits that is in neither your profile, your context
  documents nor the posting. Digits only: "twenty percent" is a claim, not a
  token, and it is the audit that has to catch it
- a sentence about sponsorship that contradicts your profile
- more than one page

### Without an API key

Finding and gating postings need no key. Writing a letter needs one — or needs
you to write the letter yourself, in a chat window, and hand it back:

```
apply gen <slug> --llm manual     # writes out/<slug>/PROMPT.md and stops
                                  # paste it into Claude; save the reply to
                                  # out/<slug>/body.md, paragraphs separated by
                                  # blank lines, the closing last
apply gen <slug> --from-body      # lint, one-page check, then the PDFs
```

The reply also carries the two portal answers. Save them in
`out/<slug>/answers.md` under `## Why this role (short)` and `## Why this role
(long)` and `--from-body` reads them too; without that file you still get the
letter and the resume, and the portal answers stay empty.

PROMPT.md is the exact request the API would have received: the same system
prompt, the same extracts from your profile and context documents, the posting
verbatim, the same instructions about structure and sponsorship. So what you
paste into a chat window is what the tool would have sent itself, and there is
nothing else to keep in your head.

`--from-body` never rewrites your prose. With no credential anywhere it skips
the audit, records the letter `unverified` in `out/<slug>/verification.json`,
and builds both PDFs on the free checks alone. If APPLY finds a credential that
then fails — an expired key, a stale `~/.config/anthropic` — it stops rather
than quietly skipping the audit, and says so. Adding `--llm manual` to that
command renders anyway, `unverified` in the same way.

What you give up is the half that reads the letter against your record.
Nothing checks it but you, so read the draft for exactly what the auditor would
have looked for:

- a claim your profile and context documents do not support — an employer, a
  degree, a responsibility, a result
- a number written in words, which the lint does not see
- the work-authorization sentence, against what your profile says
- paragraph 4's citation: that the posting really says what you have it saying

### Cost

The ledger above says $0.50 a letter over twelve letters, on Claude Opus 5 at
high effort: 13 write calls, 16 audits and 12 revisions for $6.04. A letter the
audit passes first time is about $0.42, most of it the model's reasoning, which
bills as output; most letters take one revision, which is where the rest goes.
The source material is cached, so an audit or a revision re-reads your profile
at about a tenth of the price, and `--effort medium` roughly halves the
reasoning.

A ledger checks three ceilings before every call and records the cost after
it: per call, per run and per month (defaults $0.50, $2.00 and $15.00, set
under `budget:` in `profile.private.yaml`). When a ceiling would be crossed, the
call doesn't happen and the run carries on without that step. `apply spend`
shows where it went.

---

## The human gate

```
draft ──generate──> generated ──YOU read it──> ready ──YOU submit it──> submitted
                         │                        │
                         └────── regenerate ──────┘
submitted ──> acknowledged ──> assessment ──> interviewing ──> offer
                                                          └──> rejected
any ──> withdrawn
```

Regenerating a `ready` application sends it back to `generated` and clears the
review: a re-write needs a re-read. Every transition writes an event row, so the
log is an audit trail. `apply submit` records that you submitted the application
in the employer's portal. It contacts no one.

---

## Running unattended

`apply run` is one full pass: discover, read the alert mail, write documents for
whatever earned them, report.

`apply schedule --install --at 06:30` installs the morning job with whatever
supervises the machine:

| Platform | What gets installed | Where its output goes |
|---|---|---|
| macOS | a launchd agent, `apply.daily` | `out/run.log` |
| Linux with systemd | a user timer, `apply.timer` and `apply.service` | `journalctl --user -u apply.service` |
| Linux without systemd | one cron line, marked `# apply` | `out/run.log`, where the line redirects |

launchd and the systemd timer both catch up a run missed while the machine was
off; cron does not. `apply schedule --show` prints the file that would be
written and writes nothing, `--remove` takes it out again, and a cron removal
never touches a line without the marker.

Whoever calls it, it never:

- moves an application past `generated`
- regenerates something that already has documents
- spends past the ledger's ceilings
- does anything at all while `data/HALT` exists

When an employer is down, a letter fails to compile or the mailbox is
unreachable, it records the problem and moves on. A run that half-worked beats
a run that crashed.

A quiet run sends no notification. A system that pings every morning to say it
found nothing gets muted within a fortnight, and then the morning it matters,
nobody sees it. It interrupts only when something is ready, needs reading,
closes within seven days, or broke — a desktop banner through `osascript` on
macOS or `notify-send` on Linux. `out/LATEST_RUN.md` is written either way, and
setting `notify.ntfy_topic` adds a push to your phone.

Secrets are looked up in one order on every platform: the environment, then the
macOS Keychain, then a Secret Service keyring through `keyring` if you happen to
have it installed — it is reached by `find_spec` and is not a dependency of this
project. The scheduled run is why the store lookups exist at all. A systemd
timer and a cron line start a shell that reads no profile of yours whatsoever;
the launchd agent runs `zsh -lc`, which reads `~/.zprofile` but not `~/.zshrc`,
where an `export` usually lives. Either way the variable you exported in a
terminal is absent at 06:30, and the Keychain is not.

---

## The dashboard

`apply serve` opens it at http://localhost:8787, and prints nothing while it
runs. `--port` and `--host` move it, `--no-open` stops it opening a browser.

The pipeline is sorted by deadline and drawn as a time axis: one hairline down
the left, one tick per posting, an accent tick inside seven days, and a hollow
ring below the line for a posting with no known deadline. `ready` is the only
state that needs you, so it's the only thing on the page in colour. Each
posting's page carries the description verbatim, the letter as a PDF, what the
audit found, and your portal answers as a column of copy buttons.

---

## Commands

| | |
|---|---|
| **Daily** | |
| `apply digest` | deadlines, follow-ups due, stale drafts |
| `apply status [--all] [--track T]` | the pipeline, deadline first, with the slugs listed under it in the same order |
| `apply serve [--port N] [--host H] [--no-open]` | the dashboard, at localhost:8787; `/?track=quant` filters it |
| **Finding** | |
| `apply discover [--dry-run] [--show-rejects]` | poll every registered firm |
| `apply ingest [--imap \| --file F] [--days N]` | read Handshake and LinkedIn alert mail |
| `apply add --clipboard \| --stdin \| --file F \| --url U` | add one posting by hand; `--stdin` is the route on a machine with no clipboard |
| `apply describe <slug> --clipboard \| --stdin \| --file F` | attach the full posting to a title-only one |
| `apply rescore [--dry-run]` | run the gate again over filed drafts after it changes |
| `apply resolve <careers-url> --name N` | find a firm's job board and print its registry entry |
| `apply targets` | the registry |
| `apply search` | the gate's vocabulary, and which blocks `data/search.yaml` overrides |
| **Writing** | |
| `apply gen <slug> [--from-body] [--llm manual] [--effort E] [--to NAME]` | write and audit the letter and answers; `--llm manual` writes PROMPT.md instead |
| `apply check <slug>` | audit the current letter again |
| `apply context [pull owner/repo]` | the source material Claude reads |
| `apply spend [--ledger]` | model spending against the ceilings |
| **Applying** | |
| `apply show <slug> [--jd]` | everything about one posting |
| `apply review <slug>` | you've read it: `generated → ready` |
| `apply fields <slug> [--plain]` | portal answers, for copying |
| `apply open <slug>` | the folder with the PDFs |
| `apply submit <slug>` | you submitted it: `ready → submitted` |
| `apply mark <slug> <outcome>` | `ack`, `oa`, `interview`, `offer`, `reject`, `withdrawn` |
| `apply followup <slug> "note" [--in N]` | queue a reminder; `--done` clears them |
| **Unattended** | |
| `apply run [--dry-run] [--limit N] [--notify]` | one full pass |
| `apply schedule [--show \| --install \| --remove] [--at HH:MM]` | the morning job: launchd, a systemd user timer, or cron |
| `apply runs` | what past runs did |
| **Upkeep** | |
| `apply setup [--persona] [--force]` | write `data/profile.yaml` from nine questions, and `data/search.yaml` from the city among them; `--persona` writes the example person instead |
| `apply doctor` | what's missing |
| `apply init` · `apply seed` · `apply rm <slug>` | create the database, load examples, delete |

---

## Layout

```
data/profile.example.yaml     the persona a fresh clone starts from
data/*.example.yaml           the shape of the files you write for yourself
data/examples/                two invented postings for `apply seed`
src/apply/search.defaults.yaml  the gate's shipped vocabulary
src/apply/search.py           that vocabulary, plus data/search.yaml over it
src/apply/score.py            the free relevance gate — the algorithm
src/apply/sources/            job-board adapters and alert-mail parsing
src/apply/discover.py         polling, alert ingestion, deduplication
src/apply/writer.py           the write, audit and revise loop
src/apply/generate.py         lint, typesetting, PDFs
src/apply/secrets.py          where a secret comes from, in one order
src/apply/schedule.py         launchd, systemd user timer, cron
src/apply/run.py              the unattended pass
src/apply/outbound.py         every host the system may reach, and why
templates/letters|resumes/    LaTeX, one letter template per track
templates/web/                the dashboard
tools/numbers.py              every figure this README quotes
tools/synthesize_corpus.py    writes the frozen scoring corpus the tests assert
tools/freeze_scores.py        writes the owner's own corpus, which stays local
tools/autofill.user.js        optional userscript: fills a portal, never clicks
docs/                         finding postings, and the two alert-mail guides
tests/fixtures/gate_corpus.json   every configured pattern, scored and frozen
data/profile*.yaml, data/employers.yaml, data/search.yaml, data/apply.db, out/
                              yours, and gitignored
```

---

## Design decisions

1. **The letters are written by Claude, not composed.** An earlier version
   assembled letters from sentences stored in the profile, and they read as
   templates. The profile now holds a brief of instructions; the audit and the
   lint are what make a model-written letter safe to send.
2. **The gate's vocabulary is data, its algorithm is code.** Which places score
   and which titles match were literals in `score.py`, which made retuning a
   patch. They are YAML now, and the move is pinned by a frozen corpus,
   `tests/fixtures/gate_corpus.json`, asserted verdict by verdict and reason by
   reason, so it is provable that no verdict changed on the way. The corpus is
   synthesised from the vocabulary itself: for each of the 228 configured
   patterns, a title or a location built out of that pattern; near-misses for
   the boundaries and lookarounds a transcription would quietly drop ("Rising
   Senior Summer Analyst" is not a senior role, "Basic Materials" is not an ASIC
   job); and the rules `score.py` keeps that no YAML configures. 279 cases, and
   a test that fails when the YAML grows an entry nobody has rerun the generator
   against. It used to be 826 real postings with the firms' names cut out, which
   was both less complete and less safe. Less complete: read as the gate reads
   them, those 826 exercised 90 of the 228 entries — the whole seniority block
   was among the 138 they never touched, so a lookbehind dropped from it moved
   nothing. Less safe: cutting names out is a denylist, sub-brands and addresses
   survive one, and because the employer column groups rows, a single survivor
   names every other row of that firm. Who is on the list is strategy, not code.
   The real corpus is still written — `tools/freeze_scores.py` — and it stays on
   the owner's machine, because it is the only place the rules that read a
   description can be checked against real descriptions; the test that uses it
   skips itself on a clone.
3. **Resume templates are rendered, not static.** A static `.tex` would have to
   embed phone, address and GPA, which live in the gitignored overlay.
4. **A figure from the posting counts as sourced.** Quoting the job description
   is not inventing, and paragraph four often needs to. A figure from nowhere
   still fails.
5. **No front-end framework.** A CDN script tag would break the local-first
   premise. State changes are form posts, and the only scripted interaction is
   the copy button.
6. **Deadlines beyond the digest's horizon still appear,** quietly, under
   *Further out*. Not urgent shouldn't mean invisible.

---

## Development

```bash
uv run pytest -q
```

529 tests. Without TeX, the five that compile a PDF skip themselves; without
the owner's local scoring corpus, one more does. They never touch the Anthropic
API — the key is stripped, the secret lookup is blocked and the one function
that makes calls is tripwired — and every one of them runs against a temporary
data directory and a temporary `out/`, so what is in `data/` changes nothing.
That last part is the reason `apply setup` can write you a `data/search.yaml`
for your own city without turning the suite red. The profile the tests read is a
frozen copy in `tests/fixtures/`: the shipped persona, Rae Mercer, and a test
refuses any file here that describes a real person instead.
`tests/test_acceptance.py` holds the original specification's acceptance
checks. `tests/test_fresh_clone.py` is the quick start above, run as a test on
an empty directory.

`.github/workflows/tests.yml` runs the suite on Ubuntu and macOS, on Python
3.11 and 3.13, plus `uvx ruff check --select F` and the quick start as a shell
script on both platforms — and then, on one of them, the suite a second time on
the checkout the quick start just wrote to, which is the state you are in after
following it. It triggers on pull requests and on pushes to the default branch —
so it has not run on this branch, which has not been pushed.

The two postings in `data/examples/` are invented — Quillon Asset Management and
Ashcombe Trust do not exist, and neither do the roles, the deadlines or the pay.
They are written in the register of a real listing so that the parser, the gate
and the lint have something of the right shape to work on, and so that nothing
in this repository is a job description somebody else wrote.

## License

MIT — see [LICENSE](LICENSE).
