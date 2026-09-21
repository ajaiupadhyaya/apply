# LinkedIn job alerts

APPLY never scrapes LinkedIn — its search pages sit behind an auth wall, its
terms forbid scraping, and it bans accounts for it. It doesn't need to: LinkedIn
will email you every new match for a saved search, and APPLY reads that mail.

Setup takes about fifteen minutes, once.

---

## 0. Where the mail goes — already sorted

Your LinkedIn account emails **upadhyayaak2@vcu.edu**, the same inbox APPLY
reads and the one Handshake alerts already land in. Nothing to forward.

One thing to check: no LinkedIn email has reached that inbox since October
2025, so LinkedIn's email notifications are probably switched off or throttled.

## 1. Turn job-alert email on

**Me → Settings & Privacy → Notifications → Searching for a job.** Find **Job
alerts** and make sure **Email** is on. While you're there, you can turn *Job
recommendations* on as well — APPLY reads those too (they come from
`jobs-listings@linkedin.com`), though they're less targeted.

LinkedIn moves these menus around; if the labels differ, look for the setting
that controls job-alert *email* specifically, not just in-app notifications.

## 2. Create the alerts

For each search below:

1. Open **Jobs** and type the keywords into the search box. LinkedIn accepts
   Boolean: quotes, `OR`, `AND`, `NOT` and parentheses.
2. Set the location.
3. Under **All filters**: *Date posted* → Past week; *Experience level* → the
   levels shown; *Job type* as shown.
4. Flip the **Set alert** switch at the top of the results.
5. In the alert's settings, choose **Daily** and **Email and notification**.

| # | Keywords | Location | Experience level |
|---|---|---|---|
| 1 | `("summer analyst" OR "summer associate" OR "summer intern") AND 2027` | New York City Metropolitan Area | Internship |
| 2 | `("analyst program" OR "graduate program" OR "new grad" OR campus) AND (analyst OR finance)` | New York City Metropolitan Area | Entry level |
| 3 | `"investment banking" OR "M&A" OR "private equity" OR "sales and trading"` | New York City Metropolitan Area | Internship, Entry level |
| 4 | `quantitative AND (research OR analyst OR trader)` | New York City Metropolitan Area | Internship, Entry level |
| 5 | `"research analyst" OR "research assistant" OR economist OR econometrics` | New York City Metropolitan Area | Entry level |
| 6 | `"risk analyst" OR "credit analyst" OR "investment analyst" OR "portfolio analyst"` | New York City Metropolitan Area | Entry level |
| 7 | `(predoctoral OR "pre-doctoral" OR "research assistant") AND (economics OR finance)` | United States | Internship, Entry level |
| 8 | `(finance OR investment OR research) AND (intern OR "part-time")` | Richmond, Virginia | Internship, Part-time |
| 9 | `("business analyst" OR "strategy analyst" OR "data analyst") NOT engineer` | New York City Metropolitan Area | Entry level |

These mirror what the scorer rewards: New York first, finance and research
roles, 2027 timing, pre-docs anywhere, term-time work near Richmond, and
technology roles only on the analysis side of the line.

Better to keep nine precise alerts than one broad one. Every alert email costs
nothing to read, but a broad search floods the inbox with roles the gate will
reject anyway.

## 3. What happens to the mail

```
apply ingest --file export.json     # when Claude exports it for you
apply ingest --imap                 # read the inbox directly
apply run                           # the overnight pass does it on its own, once IMAP is set up
```

Each alert is parsed card by card — title, firm, location — and goes through the
same gate as everything else. Along the way:

- **Your target firms are recognised under LinkedIn's spellings.** "J.P. Morgan"
  and "JPMorgan Chase & Co." both resolve to the JPMorgan registry entry, pick up
  its priority, and collapse with the copy from JPMorgan's own job board rather
  than being filed twice. Add spellings under `aliases:` in `employers.yaml`.
- **Firms you haven't registered are listed after each ingest**, with the
  command that would register them. That's how LinkedIn grows your registry:
  a firm that keeps appearing is worth `apply resolve`-ing, after which its
  postings arrive with full descriptions.
- **Re-posts are flagged.** A card that says "Jobs via eFinancialCareers" is a
  job board relaying someone else's posting, and isn't treated as the firm.
- **Every tracking parameter is stripped.** LinkedIn's links carry a one-time
  sign-in token; nothing with a token in it is stored.
- **Alerts older than three weeks are skipped** by the overnight run, since the
  roles they list have usually closed.

## 4. The one manual step: descriptions

A LinkedIn alert carries the title, the firm and the location — never the job
description, which sits behind LinkedIn's login. Without a description no letter
can be written, so these postings are filed for you to look at, never written
up automatically.

When one is worth pursuing:

1. Open its link (`apply show <slug>` prints it).
2. Copy the whole posting.
3. `apply describe <slug> --clipboard`

That attaches the text, reads the deadline and pay out of it, and re-scores the
posting against the full description. Then `apply gen <slug>` as usual.

## 5. Unattended

The overnight run reads mail over IMAP, which needs a Gmail **app password** —
not your account password:

1. On your VCU Google account: **myaccount.google.com → Security → 2-Step
   Verification → App passwords**. Create one called `apply`.
2. Store it in the Keychain (it prompts, so it never enters your shell history):

   ```bash
   security add-generic-password -U -a "$USER" -s APPLY_IMAP_PASSWORD -w
   ```

APPLY reads it from the Keychain directly, so the scheduled job finds it even
though launchd never reads `~/.zshrc`.

If VCU's Google Workspace doesn't offer app passwords, the option won't appear.
Then the overnight run still polls every firm in your registry on its own, and
alert mail gets picked up whenever Claude exports it for you.

## If something breaks

LinkedIn will change its email layout eventually. When it does, `apply ingest`
prints a **canary** line — *a LinkedIn job email parsed to nothing* — rather
than silently finding no jobs. The fix is a small change to
`src/apply/sources/alerts.py`, made against the new email.
