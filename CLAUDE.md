# APPLY — agent instructions

## This repository is public
- Never commit personal data or strategy. Everything a user writes for
  themselves is gitignored and stays that way: `data/profile.yaml`,
  `data/profile.private.yaml`, `data/employers.yaml`, `data/search.yaml`,
  `data/alerts.json`, `data/context/*`, `data/apply.db`, `data/HALT`, `out/`.
  `tests/test_fresh_clone.py` asserts the list; add to both or neither.
- `data/profile.example.yaml` is the scaffold a fresh clone starts from. The
  persona in it — Rae Mercer — is fictional and must stay fictional: no real
  person's name, school, employer or link ever goes in that file, and
  `tests/test_setup.py` checks it does not.
- Example files (`*.example.yaml`) show the shape of a file, never its real
  contents. Use placeholder or clearly illustrative values.
- `tests/fixtures/gate_corpus.json` is synthesised from
  `src/apply/search.defaults.yaml` — invented firms, titles assembled from the
  gate's own patterns — and frozen. Never edit it by hand and never derive it
  from a real pipeline: rerun `tools/synthesize_corpus.py` and read the diff,
  which is the list of verdicts your change moved. Anything made from real
  postings (`tools/freeze_scores.py`) is gitignored and stays local.
- A fixture made from real mail has every tracking parameter redacted —
  LinkedIn's links carry one-time sign-in tokens — and no third party's name.
- The author's live `data/` and `out/` are not the repository's to change.
  Read them if a figure needs recomputing (`tools/numbers.py` opens the
  database read-only); never write to them.
- Before committing, check the staged diff for all of the above.

## Never
- Submit an application. Nothing transmits to an employer: every module that
  sends a request is declared in `src/apply/outbound.py` with the reason its
  hosts are not employers, and the test suite fails on an undeclared one.
- Scrape or authenticate against Handshake, LinkedIn or Indeed. Their postings
  arrive by email alert or by paste.
- Store credentials, SSN, DOB, or bank details anywhere in this repo. Keys are
  looked up at call time by `apply.secrets.lookup` — the environment, then the
  macOS Keychain, then a `keyring` backend — and nothing here writes one.
- Promote an application to `ready` or `submitted` without an explicit human action.
- Write a fact into a generated document that is not in the profile, the
  context documents, or the posting.

## Always
- Keep jd_raw verbatim. Never discard source text; `apply describe` appends.
- Log an event row on every status transition.
- Run the lint and the one-page check before marking anything generated.
- Reset ready → generated whenever documents are regenerated.
- Prefer deterministic parsing; use the LLM only where regex fails.

## How letters are written
- Claude writes every letter and portal answer (src/apply/writer.py); an
  independent request audits it. Do not reintroduce template sentences in
  profile.yaml — the `writing:` block is instructions, never prose to paste.
- The hard rules live in writer.WRITER_RULES and generate.lint. The brief may
  change voice and emphasis; it may never loosen grounding.

## Tests
- Tests never call the API. tests/conftest.py strips the key, blocks the
  Keychain lookup, and trips on llm.call; use the FakeClaude fixture.
- Tests run against tests/fixtures/profile.yaml, a frozen copy, never the live
  data/profile.yaml. Anything date-dependent pins its date.
- The suite must pass on Python 3.11 and 3.13 (CI runs both).

## Conventions
- Slugs: <company>-<role>-<year>, lowercase, hyphenated.
- Dates: ISO 8601 in the DB. Human formatting only at render time.
- No new runtime dependencies without asking the owner.
- Use `uv` for everything: `uv run apply ...`, `uv add ...`, `uv sync`. Never bare pip.

## Deliberate deviations from the original spec
0. Letters are written by Claude from a brief, not composed from stored
   sentences. See README "Writing".
1. Resume templates are `.tex.j2`, not `.tex`: a static file would have to embed
   phone, address and GPA, which live in the gitignored private overlay.
2. The hallucination guard accepts a figure found in the profile, the context
   documents, or the posting. A figure quoted from the posting is sourced.
