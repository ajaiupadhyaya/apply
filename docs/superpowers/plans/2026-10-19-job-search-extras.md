# Job-search extras: what ai-job-search does that APPLY does not

Date: 2026-10-19 · Branch: `job-search-extras` (stacked on `one-main`, PR #7)

## Where things stand

- PR #7 (`one-main`) puts every open branch, plus PR #6, into one `main`. CI is
  green on macOS, Linux and Windows, and the owner's corpus scores the same.
  What is left is the owner's review and merge, restoring `data/profile.yaml`
  and `data/alerts.json` from the backup, and deleting the superseded branches.
- PR #6 already took five ideas from MadsLorentzen/ai-job-search: the ATS
  read-back, keyword coverage, ASCII date ranges, the source-host check, and the
  `stats`/`gaps` views.

## What else is worth taking

| Their feature | APPLY today | Plan |
|---|---|---|
| `/interview`: a prep pack for one tracked application, kept consistent with what was submitted | nothing | **F1** `apply interview <slug>` |
| `/outcome followup`: a drafted follow-up note for an application that has gone quiet | `followup` only queues a reminder | **F2** `apply followup <slug> --draft` |
| `no_response` as a final outcome, and the stale sweep at 60+ days | `digest` lists "submitted 14+ days, no reply"; there is no ghosted outcome | **F3** `apply mark <slug> no_response`, plus a digest line suggesting it |
| `/rank` sweep: expired vs unreachable postings | nothing re-checks a posting once it is filed | **F4** `apply sweep`: re-check unsubmitted postings at the source |
| robots.txt check before fetching a page | `pages.py` says to check by hand | **F5** `resolve` checks robots.txt before it adds a careers page |

Not taken, and why:

- **Company research cache.** Letters may cite only the profile, the context
  documents and the posting (CLAUDE.md). Researched claims would break that rule.
- **Salary lookup, the Danish portals, the Notion and Gmail sync.** Out of scope
  for this owner, or they duplicate `ingest`.
- **The HTML report.** `apply serve` already does this.

## Rules every feature keeps

- Nothing is sent or submitted. Drafted text is printed and saved, never mailed.
- Anything Claude writes is grounded the way the letters are. Every figure must
  come from the profile, the context documents, the posting, or what was
  already submitted. An independent request audits the claims. If unsupported
  claims are still there after the last draft, nothing is written.
- Tests use FakeClaude and never call the API. `uv run pytest -q` stays green
  after every feature, and each feature is its own commit.
- No new dependencies.

## F1 — `apply interview <slug> [--stage S] [--with "Name, Title"]`

- `src/apply/interview.py`:
  - a `Prep` schema: likely questions, each with its reason and an answer
    outline; STAR stories built from profile facts; a consistency brief (claims
    in the submitted documents an interviewer will probe); questions to ask.
  - `INTERVIEW_RULES`: the same grounding rule as the letters. A gap gets an
    honest bridge answer, never invented experience.
- Sources: the system block shared with the writer, the posting, and what was
  submitted (`body.md`, `answers.md`, and the resume PDF's text layer through
  `ats.extract`).
- Loop:
  1. write;
  2. free digit check against every source;
  3. `PrepAudit` request, which lists unsupported claims;
  4. one revision.
  Unsupported claims left after that mean no file.
- Writes `out/<slug>/interview-<stage>.md` and logs a note event. Budget-checked
  and recorded like `gen`.

## F2 — `apply followup <slug> --draft`

- A short follow-up email in formal register.
- Passes the letter lint: prohibited phrases, register, and unsourced figures.
- Printed and saved to `out/<slug>/followup-<date>.md`. Never sent.

## F3 — `no_response`

- `Status.NO_RESPONSE` is final. It is reachable from `submitted` and
  `acknowledged`, and only by `apply mark`.
- `stats` counts it as a closed application.
- `digest` suggests it for anything submitted 60+ days ago with no reply.

## F4 — `apply sweep [--dry-run]`

- Re-fetches the URL of each open, unsubmitted posting.
- **Closed** means 404/410, or a redirect to a listing page. It is logged as an
  event and shown in `digest` and `show`. The status never changes; the owner
  withdraws it.
- **Unreachable** (timeouts, 403, 5xx) is reported and changes nothing.

## F5 — robots.txt

- `resolve.find` reads the careers host's robots.txt with the standard library's
  `urllib.robotparser`.
- A disallowed path is reported and not added.
