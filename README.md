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
write    Claude drafts the letter and portal answers from your profile    ~$0.40
audit    a second request checks each claim against your sources
you      read it (apply review), then submit it yourself (apply submit)
```

It was built for one person's search — a 2027 finance job hunt centred on New
York — and is tuned for it in a few clearly marked places. See
[Retuning it](#retuning-it).

---

## What it will not do

Enforced in code and in tests, not just promised here.

| Never | How |
|---|---|
| Submit an application | Nothing transmits to an employer. Every module that sends a request is declared in `src/apply/outbound.py` with the reason its hosts are not employers, and the suite fails on an undeclared one. There is no browser driver in the codebase. |
| Scrape Handshake, LinkedIn or Indeed | Their postings arrive through the alert emails they already send you, or by paste. `apply add --url` refuses Handshake outright. |
| Hold a credential in a file | The Anthropic key and the IMAP app password live in the macOS Keychain and are read at call time. |
| Move an application without you | `ready` accepts only the `review` action and `submitted` only `submit`; every other caller is refused by `db.transition`. |
| Claim what you haven't done | The lint fails any figure found in neither your profile, your context documents nor the posting; the audit catches every other unsupported claim. Either failure means no PDF. |

---

## Quick start

Needs Python 3.11+, [uv](https://docs.astral.sh/uv/), a TeX install and an
Anthropic API key. The scheduler and the Keychain lookup are macOS-specific;
everything else runs anywhere.

```bash
git clone https://github.com/ajaiupadhyaya/apply && cd apply
uv sync
brew install --cask mactex-no-gui                                # if pdflatex is missing
security add-generic-password -U -a "$USER" -s ANTHROPIC_API_KEY -w   # prompts for the key
uv run apply init
```

Then make it yours. Three files hold everything about you:

| File | Holds | Tracked? |
|---|---|---|
| `data/profile.yaml` | your facts — education, experience, projects, skills, work authorization, availability — and a writing brief | yes; this one is its author's, so replace it |
| `data/profile.private.yaml` | phone, address, GPA, target list, budget | no — copy the `.example` |
| `data/employers.yaml` | which firms to poll, and how | no — copy the `.example` |

`uv run apply doctor` lists whatever is still missing, and `uv run apply seed`
loads two example postings to try things on. To run `apply` from any folder:

```bash
echo "alias apply='uv run --project $(pwd) apply'" >> ~/.zshrc
```

---

## Finding postings

### Firms' own job boards

`apply discover` polls every firm in `data/employers.yaml` through the public
API behind its careers page. It calls no model, so it costs nothing.

| Board | Endpoint | Notes |
|---|---|---|
| Greenhouse | `boards-api.greenhouse.io` | one request per firm, descriptions included |
| Lever | `api.lever.co/v0/postings` | one request per firm |
| Ashby | `api.ashbyhq.com/posting-api` | one request per firm |
| Workday | the `/wday/cxs/` endpoint its own careers page calls | list, then one request per posting; carries real deadlines |
| Oracle Recruiting Cloud | the REST resource its careers page calls | 200 postings a request, then one per posting; carries real close times |
| Embedded page data | the `__NEXT_DATA__` blob a Next.js careers page renders from | one request per firm, descriptions included; for firms with no board API |

A firm whose careers site sits behind bot protection (a Cloudflare challenge,
say) is not polled. Getting past that would mean pretending to be a browser,
which is the line this project doesn't cross; those firms arrive through alert
mail instead.

Adding a firm doesn't mean reading devtools:

```
apply resolve <careers page> --name "Firm"
```

reads the page, identifies the board, confirms it answers, and prints the block
to paste into the registry.

### Alert mail

Handshake and LinkedIn email you new matches for saved searches. `apply ingest`
reads that mail, over IMAP or from an export, and files the postings. The two
setup guides cover which searches to save:

- [docs/handshake-alerts.md](docs/handshake-alerts.md)
- [docs/linkedin-alerts.md](docs/linkedin-alerts.md)

Firms in your registry are recognised under other spellings ("J.P. Morgan" is
JPMorgan), and a posting seen in both an alert and on the firm's own board
collapses into one. Firms you haven't registered are listed after each ingest,
with the command to add them. LinkedIn's links carry one-time sign-in tokens;
those are stripped before anything is stored.

An alert carries the title but never the description, so nothing arriving this
way is written up automatically. When one is worth pursuing:

```
apply describe <slug> --clipboard
```

attaches the full posting, reads its deadline and pay, and re-scores it.

### By hand

`apply add --clipboard` takes any posting you've copied.

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

Hard rejects, each of which names itself: senior titles, engineering roles,
off-function roles, anywhere outside the US, three or more years of required
experience, a required advanced degree or a title naming one ("Ph.D. Intern",
"MBA Associate" — pre-doctoral roles pass), and programmes aimed at a class year
other than yours. That last one is derived from your graduation date rather than
stored, because a stored class year is wrong within a year.

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
at), `reject` (dropped, with the reason). On one live pass across four
employers: 555 fetched, 497 unique, 447 rejected before any model was called.

### Retuning it

The scorer is tuned for its author's search. New York is the heaviest single
signal, and the timing patterns look for 2026–27 roles. Both live in
`src/apply/score.py` — the geography block, `ROLE_FIT` and `TIMING` — and the
thresholds are in `profile.private.yaml`.

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

Your own edits are audited but never rewritten:

```
apply gen <slug>                  # write, check, audit, revise
apply gen <slug> --from-body      # check and render your edits to body.md
apply check <slug>                # audit again, change nothing
apply gen <slug> --llm manual     # write PROMPT.md to paste into Claude by hand
```

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
- a figure in neither your profile, your context documents nor the posting
- a sentence about sponsorship that contradicts your profile
- more than one page

### Cost

Measured on Claude Opus 5 at high effort, a letter verified on its first draft
costs about $0.42; most of that is the model's reasoning, which bills as output.
One that needs revising costs more. The source material is cached, so an audit
or a revision re-reads your profile at about a tenth of the price. `--effort
medium` roughly halves the reasoning.

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
whatever earned them, report. `apply schedule --install --at 06:30` runs it every
morning through launchd, which survives reboots and catches up a missed run
after the laptop wakes.

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
closes within seven days, or broke. `out/LATEST_RUN.md` is written either way,
and setting `notify.ntfy_topic` adds a push to your phone.

Keys are read from the Keychain rather than the environment for a reason:
launchd starts a non-interactive shell, which never reads `~/.zshrc`, so an
exported variable simply isn't there at 06:30.

---

## The dashboard

`apply serve` opens it at http://localhost:8787.

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
| `apply status [--all] [--track T]` | the pipeline, deadline first; one track with `--track` |
| `apply serve` | the dashboard, at localhost:8787; `/?track=quant` filters it |
| **Finding** | |
| `apply discover [--dry-run] [--show-rejects]` | poll every registered firm |
| `apply ingest [--imap \| --file F] [--days N]` | read Handshake and LinkedIn alert mail |
| `apply add --clipboard \| --file \| --url` | add one posting by hand |
| `apply describe <slug> --clipboard` | attach the full posting to a title-only one |
| `apply rescore [--dry-run]` | run the gate again over filed drafts after it changes |
| `apply resolve <careers-url> --name N` | find a firm's job board and print its registry entry |
| `apply targets` | the registry |
| **Writing** | |
| `apply gen <slug> [--from-body] [--effort E] [--to NAME]` | write and audit the letter and answers |
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
| `apply schedule [--show \| --install \| --remove] [--at HH:MM]` | the morning job |
| `apply runs` | what past runs did |
| **Upkeep** | |
| `apply doctor` | what's missing |
| `apply init` · `apply seed` · `apply rm <slug>` | set up, load examples, delete |

---

## Layout

```
data/profile.yaml             your facts and writing brief (tracked)
data/*.example.yaml           the shape of the private files
data/examples/                two example postings for `apply seed`
data/context/                 source material for the writer (gitignored)
src/apply/sources/            job-board adapters and alert-mail parsing
src/apply/score.py            the free relevance gate
src/apply/discover.py         polling, alert ingestion, deduplication
src/apply/writer.py           the write, audit and revise loop
src/apply/generate.py         lint, typesetting, PDFs
src/apply/run.py              the unattended pass
src/apply/outbound.py         every host the system may reach, and why
templates/letters|resumes/    LaTeX, one letter template per track
templates/web/                the dashboard
tools/autofill.user.js        optional userscript: fills a portal, never clicks
out/<slug>/                   everything generated (gitignored)
```

---

## Design decisions

1. **The letters are written by Claude, not composed.** An earlier version
   assembled letters from sentences stored in the profile, and they read as
   templates. The profile now holds a brief of instructions; the audit and the
   lint are what make a model-written letter safe to send.
2. **Resume templates are rendered, not static.** A static `.tex` would have to
   embed phone, address and GPA, which live in the gitignored overlay.
3. **A figure from the posting counts as sourced.** Quoting the job description
   is not inventing, and paragraph four often needs to. A figure from nowhere
   still fails.
4. **No front-end framework.** A CDN script tag would break the local-first
   premise. State changes are form posts, and the only scripted interaction is
   the copy button.
5. **Deadlines beyond the digest's horizon still appear,** quietly, under
   *Further out*. Not urgent shouldn't mean invisible.

---

## Development

```bash
uv run pytest -q
```

310 tests, run on Python 3.11 and 3.13 in CI. They never touch the Anthropic
API — the key is stripped and the one function that makes calls is tripwired —
and they run against a frozen profile in `tests/fixtures/`, so replacing
`data/profile.yaml` breaks nothing. `tests/test_acceptance.py` holds the
original specification's acceptance checks. Tests that compile a PDF skip
themselves without TeX.

The postings in `data/examples/` are representative text for trying the tool,
not live listings.

## License

MIT — see [LICENSE](LICENSE).
