# APPLY — agent instructions

## Never
- Submit an application. No automated POST, click, or scheduled submission.
- Scrape or authenticate against Handshake.
- Store credentials, SSN, DOB, or bank details anywhere in this repo.
- Promote an application to `ready` or `submitted` without an explicit human action.
- Write a fact into a generated document that is not present in profile.yaml.

## Always
- Keep jd_raw verbatim. Never discard source text.
- Log an event row on every status transition.
- Run the prohibited-words lint and the 1-page check before marking generated.
- Reset ready → generated whenever documents are regenerated.
- Prefer deterministic parsing; use the LLM only where regex fails.

## Conventions
- Slugs: <company>-<role>-<year>, lowercase, hyphenated.
- Dates: ISO 8601 in the DB. Human formatting only at render time.
- No new runtime dependencies without asking the owner.
- Use `uv` for everything: `uv run apply ...`, `uv add ...`, `uv sync`. Never bare pip.

## How letters are written
- Claude writes every letter and portal answer (src/apply/writer.py); an
  independent request audits it. Do not reintroduce template sentences in
  profile.yaml — the `writing:` block is instructions, never prose to paste.
- The hard rules live in writer.WRITER_RULES and generate.lint. The brief may
  change voice and emphasis; it may never loosen grounding.
- Tests never call the API. tests/conftest.py strips the key, blocks the
  Keychain lookup, and trips on llm.call; use the FakeClaude fixture.

## Deliberate deviations from the original spec
0. Letters are written by Claude from a brief, not composed from stored
   sentences. See README "How the letters get written".
1. Resume templates are `.tex.j2`, not `.tex`. A static `.tex` would have to embed
   phone/address/GPA, which live in the gitignored private overlay. Rendering them
   keeps private facts out of version control.
2. The number/date hallucination guard allows a token that appears verbatim in
   EITHER profile.yaml OR the posting's `jd_raw`. A figure quoted from the job
   description is sourced, not hallucinated, and paragraph 4 often needs one.
