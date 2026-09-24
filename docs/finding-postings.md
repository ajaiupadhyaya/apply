# Finding postings

Three ways in: a firm's own job board, the alert mail Handshake and LinkedIn
already send you, and paste. All three end in the same place — a row in the
database, scored by [the gate](../README.md#the-gate).

## Firms' own job boards

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
| Eightfold | the requisition API its careers page reads | ten postings a request, then one per posting; some boards are bot-protected |

A firm whose careers site sits behind bot protection (a Cloudflare challenge,
say) is not polled. Getting past that would mean pretending to be a browser,
which is the line this project doesn't cross; those firms arrive through alert
mail instead.

To register a firm:

```
uv run apply resolve <careers page> --name "Firm"
```

reads the page, works out which board is behind it, confirms the board answers,
and prints the block to paste into `data/employers.yaml`. `apply targets` lists
what is registered. `data/employers.example.yaml` shows the shape of an entry
for each board.

## Alert mail

`apply ingest` reads Handshake and LinkedIn alert mail over IMAP or from an
export, and files the postings. Firms in your registry are recognised under
other spellings, and a posting seen in both an alert and on the firm's own
board collapses into one. Firms you haven't registered are listed after each
ingest, with the command to add them. LinkedIn's links carry one-time sign-in
tokens; those are stripped before anything is stored.

Which searches to save, and how to get the mail somewhere APPLY can read it,
are in [handshake-alerts.md](handshake-alerts.md) and
[linkedin-alerts.md](linkedin-alerts.md).

An alert carries the title but never the description, so nothing arriving this
way is written up automatically. When one is worth pursuing:

```
apply describe <slug> --clipboard          # or --stdin, or --file
```

attaches the full posting, reads its deadline and pay, and re-scores it.

## By hand

`apply add` takes a posting four ways, and `apply describe` takes the first
three:

```
apply add --clipboard                      # whatever you have just copied
apply add --stdin < posting.txt            # or a pipe: pbpaste | apply add --stdin
apply add --file posting.txt
apply add --url https://…                  # a firm's own careers page
```

`--clipboard` reads through whichever tool the machine has: `pbpaste` on macOS,
then `wl-paste`, `xclip`, `xsel` on Linux, first one on `PATH` wins. None of
them is a dependency of this project. A machine with none of them — a server, a
container, an SSH session — gets a refusal that names `--stdin`, which works
everywhere.

`--url` refuses Handshake, LinkedIn and Indeed, subdomains included, and prints
both paste routes instead. Those sites are read through the alert mail they
send you.
