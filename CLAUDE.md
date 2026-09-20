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

## Two deliberate deviations from the original spec
1. Resume templates are `.tex.j2`, not `.tex`. A static `.tex` would have to embed
   phone/address/GPA, which live in the gitignored private overlay. Rendering them
   keeps private facts out of version control.
2. The number/date hallucination guard allows a token that appears verbatim in
   EITHER profile.yaml OR the posting's `jd_raw`. A figure quoted from the job
   description is sourced, not hallucinated, and paragraph 4 often needs one.
