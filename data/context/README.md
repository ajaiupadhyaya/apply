# Context documents

Everything in this folder is source material Claude reads before writing an
application — and therefore something a letter is **allowed to claim**. The
auditor checks every sentence against the profile, these files and the posting,
and anything it cannot trace is sent back for revision.

So curate it like you would a reference list: only what you would stand behind
in an interview.

- `apply context` — list what is here, and how much of the budget it uses
- `apply context pull owner/repo` — fetch a GitHub README, keep the introduction,
  every heading and each section's opening, in your own words, and file it here
- or drop any `.md` file in by hand: a bio, notes on a project, a writeup

Files here are gitignored (except this one), because notes and bios tend to be
personal. Up to 14,000 characters per file and 42,000 in total are read; the
block is cached, so after the first call in a run it costs about a tenth as much.
