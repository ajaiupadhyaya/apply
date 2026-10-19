# Design: a repo a stranger can run, and an investor can read

**Date:** 2026-09-23
**Status:** approved, ready for an implementation plan

## The problem

APPLY works. It polls 152 firms across five job-board types, files what
survives a free relevance gate, has Claude write and audit a letter, and stops
at the submit button. 396 tests hold that shape in place.

But the repository is still one person's tool wearing a public licence. Three
things break for anyone else:

1. **`apply init` scaffolds the author's life.** `data/profile.yaml` is tracked
   and holds his real education, projects, employer, email and writing brief. A
   stranger's first act is deleting a biography.
2. **The gate is tuned in Python.** The New York weighting, the finance role
   list and the 2026–27 timing patterns are literals in `src/apply/score.py`.
   Someone hunting design roles in Berlin edits source.
3. **The unattended path is macOS-only.** `apply schedule` writes a launchd
   plist. Linux has no route to the thing the project is for: waking up to a
   filled pipeline.

And for a reader deciding whether this is serious work, the README opens with
prose rather than evidence. The numbers exist — they have never been counted.

## Goals

- A stranger clones, runs one command, answers a few questions, and has a
  working profile and a filled pipeline within ten minutes.
- Retuning the gate for another city, field or graduation year means editing
  YAML, never Python.
- macOS and Linux both reach an unattended morning run, both tested in CI.
- Every command works on a fresh clone, proven by CI rather than asserted.
- The README leads with measured numbers and screenshots of the real thing.

## Non-goals

- **Auto-submit stays unbuilt.** "Nothing transmits to an employer" is the
  project's load-bearing guarantee, enforced by `outbound.py` and the suite.
  It is also the reason this is safe to open-source. The portal field pack and
  the fill-only userscript remain the answer.
- Windows, a plugin system, a hosted site, PyPI publishing, separate
  ARCHITECTURE/CONTRIBUTING/SECURITY documents. What a cloner needs goes in the
  README.
- No new runtime dependencies. `keyring` stays optional and is only used when
  already installed.

## Work-streams

### A. Onboarding: a persona, and a wizard

**`data/profile.example.yaml`** — a complete fictional person. Not a template
of empty keys: a 2027 economics graduate in London with two projects, one job,
skills, availability, work authorization and a writing brief, so the pipeline
produces a real letter on a fresh clone. Every value obviously invented; no
real person's facts.

**`apply setup`** — the front door. Asks in order: name, email, links, school,
degree, graduation month, what kind of work, target cities, work authorization,
availability. Writes `data/profile.yaml` from the answers, then copies
`profile.private.example.yaml` and `employers.example.yaml` into place if they
are missing, and ends by running `doctor`. Flags: `--persona` writes the
fictional profile unmodified (demo and test drive), `--force` overwrites an
existing profile, `--non-interactive` takes the persona and asks nothing, which
is what CI uses.

**`data/profile.yaml` becomes untracked.** It moves to `.gitignore`; the
author's copy stays on his disk. `apply init` scaffolds from
`profile.example.yaml`. The repo stops carrying anyone's real email.

Acceptance: on a clone with no `data/profile.yaml`, `apply setup
--non-interactive && apply seed && apply status` prints a pipeline.

### B. The gate becomes configuration

`src/apply/score.py` keeps the algorithm and loses the vocabulary. A packaged
`src/apply/search.defaults.yaml` holds what is in the file today: hard-reject
patterns (seniority, off-function, too-technical, graduate programmes), the
geography blocks with their weights (NYC +25, home +15, remote +10, hub +6),
`ROLE_FIT`, `TIMING`, `TITLE_TIMING`, `CLASS_SCOPED`, thresholds. A user's
`data/search.yaml` overrides any block; `apply search` prints the gate
configuration in force and where each block came from.

The refactor must not change a single score. Before it starts, a
characterisation test scores the live corpus — every posting in the database,
with its current value and verdict — into a fixture, and asserts the new code
reproduces it exactly. That fixture is anonymised: employer names replaced,
titles kept.

Acceptance: characterisation test green; a `data/search.yaml` that moves the
geography weights to Berlin changes the verdicts, proven by a test.

### C. Linux, first-class

`apply schedule` grows a platform layer:

- macOS: the launchd plist it writes today.
- Linux: a systemd **user** timer and service written to
  `~/.config/systemd/user/`, or, when systemd is absent, a crontab line
  installed through `crontab -l | ... | crontab -`.
- `--off` removes whichever was installed; `apply runs` is unchanged.

Secrets resolve in one stated order, in one function: `ANTHROPIC_API_KEY` in
the environment, then the macOS Keychain, then `keyring` if it is installed,
and a clear instruction if none of them answer. The same order applies to
`APPLY_IMAP_PASSWORD`. Notifications use `osascript` on macOS and
`notify-send` on Linux, and stay silent rather than failing anywhere else.

CI gains an Ubuntu job. The matrix becomes {ubuntu, macos} × {3.11, 3.13}.

Acceptance: the scheduler's Linux writer is unit-tested against a fake
filesystem and a fake `crontab`; CI is green on both platforms.

### D. Completeness audit

Walk every command end to end on a fresh clone and fix or delete what is
half-built. Known candidate: the `contact` table in `db.py` that nothing
writes to — either `apply contact` exists or the table goes.

A **fresh-clone smoke test** runs in CI on both platforms: install, `apply
setup --non-interactive`, `apply seed`, `apply status`, `apply digest`, `apply
targets`, `apply fields`, `apply rescore --dry-run`, and a dashboard request
through FastAPI's test client. `gen` is excluded: it needs a key.

Acceptance: the smoke test is a CI job; no command in `--help` is undocumented
or dead.

### E. README as evidence

Replace the opening with measured numbers, each one reproducible from the
repository or the author's database, and each labelled as one person's run:

- firms in the registry by board type (152 today)
- postings filed and how they scored (826 filed today; 196 of them since
  screened out by later gate changes)
- cost per letter, computed from the ledger when the README is written, not
  quoted from memory
- tests, and the platforms they run on

Screenshots, generated from the **persona**, of the dashboard pipeline and one
posting page, plus a rendered letter PDF page. They go in `docs/img/`. No real
employer's name and none of the author's details appear in any of them.

A "Make it yours" section replaces "Retuning it": the three files, the setup
wizard, `data/search.yaml`, adding an employer with `apply resolve`.

Acceptance: every number in the README is either derivable from a command in
the README or labelled with its source and date.

## Sequencing and risk

A, B, C and E touch disjoint files and run in parallel. D depends on all of
them (it tests the finished surface), and the README's screenshots depend on A
(the persona must exist).

The one real risk is B silently changing scores. The characterisation fixture
is written and committed *before* any constant moves, and it is the gate on the
refactor.

Every work-stream keeps the suite green on 3.11 and 3.13, and none may weaken
`outbound.py`, the human gates in `db.transition`, or the lint. The acceptance
tests in `tests/test_acceptance.py` stay untouched except to add to them.

## Delivery

One PR stacked on `publish-ready` (PR #1, still open), one commit per
work-stream, review reads in order A → B → C → D → E.
