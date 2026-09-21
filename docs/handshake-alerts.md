# Getting Handshake into the pipeline, without touching Handshake

APPLY never logs into Handshake, never stores a session token, and never fetches
a page from `joinhandshake.com`. Student accounts are usually provisioned by a
university careers office, Handshake's terms prohibit automated access, and an
account flagged in October is an account you do not have in January.

The way in is that **Handshake already emails you jobs**. Reading your own inbox
is not automated access to Handshake. So the job is to make those emails
complete and frequent enough — APPLY finds them by sender and does the rest.

Everything below is a one-time setup. Budget fifteen minutes.

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

## 2. Nothing to set up in Gmail

The ingester finds Handshake and LinkedIn job mail by its sender, so there are
no labels or filters to create. If you'd rather these stopped landing in your
inbox, a Gmail filter that skips the inbox for `from:(joinhandshake.com)` is
harmless — APPLY reads archived mail too.

---

## 3. What Handshake does not cover

Handshake is broad but shallow on the firms most worth targeting: many post
only to their own job boards. Those are covered by the employer registry
(`apply targets`), which polls each firm's public job-board API directly and
does not depend on email at all.

The division of labour:

- **Employer registry** — firms you have named. Complete and structured, with
  full descriptions, and with deadlines where the job board carries them.
- **Alert mail** — everything else, including Handshake-only postings and firms
  you haven't thought to add yet. Broader and thinner, and the reason the system
  can surprise you with something good.

---

## 4. What happens to the mail

Each run of `apply ingest` (or the overnight `apply run`):

1. Finds Handshake and LinkedIn job mail by sender, and skips everything else
   those services send — application confirmations, appointment reminders,
   recruiter messages.
2. Reads each posting out of the email: employer, role, location, and pay where
   given.
3. Resolves the year of any deadline from the email's own date — "due Thu, Sep
   24" in a message sent on the 20th is unambiguous — and never guesses one
   otherwise.
4. Recognises your registry firms under other spellings, and collapses a
   posting seen both in an alert and on the firm's own board into one.
5. Scores it through the same gate as everything else, and files what survives.

Nothing is marked read or moved; the mailbox is opened read-only.

A Handshake alert gives the title and not the description, and the posting
behind it is on Handshake, which APPLY does not fetch. So these are filed for
you to open. When one is worth pursuing, copy the full posting and run
`apply describe <slug> --clipboard`, which attaches the text and re-scores it.

---

## 5. Getting the mail to APPLY

Two ways in, and the parsing is the same either way:

- **IMAP, for unattended runs.** Create a Gmail app password (myaccount.google.com
  → Security → 2-Step Verification → App passwords) and store it in the Keychain:

  ```bash
  security add-generic-password -U -a "$USER" -s APPLY_IMAP_PASSWORD -w
  ```

  `apply ingest --imap` and the scheduled run read it from there. If your
  institution's Google Workspace doesn't offer app passwords, the option simply
  won't appear.

- **An export, when Claude does the fetching.** Claude can read the same mail
  through a Gmail connector and write it to a JSON file for
  `apply ingest --file export.json`.
