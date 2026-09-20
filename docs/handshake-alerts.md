# Getting Handshake into the pipeline, without touching Handshake

APPLY never logs into Handshake, never stores a session token, and never fetches
a page from `joinhandshake.com`. Your account is provisioned by VCU Career
Services, Handshake's terms prohibit automated access, and an account flagged in
October is an account you do not have in January.

The way in is that **Handshake already emails you jobs**. Reading your own inbox
is not automated access to Handshake. So the job is to make those emails
complete, frequent enough, and easy to find — then point the ingester at one
Gmail label.

Everything below is a one-time setup. Budget twenty minutes.

---

## 1. Make Handshake send you everything you care about

Handshake's navigation moves between releases, so these are described by what
you are looking for rather than by an exact menu path.

**Create one saved search per track.** In Handshake's job search, set the filters
for a track, run it, and use the **Save search** control. Handshake will then
email you new matches for that search. Four searches keep the emails
self-sorting, which matters later when the ingester is deciding what a posting
actually is:

| Save it as | Filters to set |
|---|---|
| `apply-quant` | Keywords: quantitative, trading, research, risk, derivatives · Job type: Internship + Full-Time |
| `apply-banking` | Keywords: investment banking, M&A, private equity, corporate development |
| `apply-allocator` | Keywords: investment, endowment, asset management, manager research |
| `apply-corporate` | Keywords: financial analyst, FP&A, rotational, business analyst |

Set **Location: New York** on the first three and leave `apply-corporate` open to
Richmond and remote as well. That mirrors how the scorer weights geography, so
what arrives is already close to what survives.

**Set the frequency to daily, not instant.** An overnight run wants one digest
per search, not forty separate emails. Instant alerts will work, they are just
noisier and slower to ingest.

**Check the notification settings** for your account and make sure email is
enabled for job recommendations and saved searches. Handshake defaults some of
these to in-app only, which is invisible to anything outside Handshake.

**Turn on the employer-following alerts** for firms you care about. Following an
employer in Handshake gets you their postings even when your saved-search
keywords miss them.

---

## 2. Funnel every alert into one Gmail label

The ingester reads exactly one label. Everything else is a filter feeding it.

Create the label first: in Gmail, **Settings → Labels → Create new label**, named
`apply/alerts`. The slash makes it nest under a parent called `apply`, which
keeps it out of the way.

Then create the filters. In Gmail, **Settings → Filters and Blocked Addresses →
Create a new filter**, paste the search string into the **Has the words** box,
and on the next screen tick **Apply the label: apply/alerts** and **Skip the
Inbox**. Skipping the inbox matters — the point is that these stop interrupting
you and become a queue instead.

| Source | Paste into "Has the words" |
|---|---|
| Handshake | `from:(joinhandshake.com)` |
| LinkedIn job alerts | `from:(linkedin.com) AND subject:("job alert" OR "jobs for you" OR "new jobs")` |
| Greenhouse alerts | `from:(greenhouse.io OR my.greenhouse.io)` |
| Indeed | `from:(indeed.com) AND subject:("new jobs" OR "job alert")` |
| Catch-all for firm alerts | `subject:("job alert" OR "new opportunities" OR "jobs for you" OR "new roles")` |

Run the catch-all last and check what it caught before trusting it; it is the one
most likely to pull in something you did not mean.

**Apply the filter to existing mail.** The final screen offers "Also apply filter
to matching conversations" — tick it. That backfills the label with whatever is
already sitting in your inbox, and gives the first ingestion run something to
work with.

---

## 3. Add the sources Handshake does not cover

Handshake is broad but shallow on the firms at the top of your list — Jane
Street, IMC and Optiver post to their own boards, and BlackRock posts to Workday.
Those are already covered by the employer registry (`apply targets`), which polls
their public job-board APIs directly and does not need email at all.

The division of labour is worth being explicit about:

- **Employer registry** — firms you have named. Complete, structured, has
  deadlines where the ATS carries them. This is the reliable half.
- **Email alerts** — everything else, including the Handshake-only postings and
  the firms you have not thought to add yet. Broader, messier, and the reason the
  system can surprise you with something good.

---

## 4. What the ingester will do with them

Reading the label is the next phase of the build, so this is what to expect
rather than what exists today:

1. Read unread threads under `apply/alerts` via the Gmail connector, oldest first.
2. Pull every job link out of each email, with the surrounding text as a hint.
3. Resolve each link: follow it to the employer's real posting where that is a
   public page, and keep the email's own summary where it is not.
4. Fingerprint against everything already stored, so a role that arrives through
   both Handshake and the employer's Greenhouse board collapses to one posting.
5. Score it exactly like a registry posting — same gate, same thresholds.
6. Mark the thread read, so the next run starts where this one stopped.

A Handshake alert that points at a Handshake-hosted posting is the one case where
the link cannot be followed. Those get filed with the email's own text and the
URL, marked `⚠ description from the alert email only`, and you open Handshake
yourself to read the full posting. That is the deliberate cost of not scraping.

---

## 5. Authorising Gmail

The connector needs authorising once, interactively, from your Gmail connector
settings on claude.ai. Until then the ingester will report that Gmail is not
connected and the registry half of discovery will run on its own.

APPLY reads only the `apply/alerts` label and only marks those threads read. It
never sends, never deletes, and never reads anything outside that label.
