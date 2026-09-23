"""SQLite access layer.

One file, one user, no ORM. The only clever thing in here is transition(), which
is the single doorway to the status column and refuses anything the state machine
in models.py does not allow.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from pathlib import Path
from typing import Iterable

from .models import (
    Application,
    Event,
    EventKind,
    Followup,
    Posting,
    Row,
    Status,
    check_transition,
)
from .profile import data_dir

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS posting (
  id            INTEGER PRIMARY KEY,
  slug          TEXT UNIQUE NOT NULL,
  company       TEXT NOT NULL,
  role          TEXT NOT NULL,
  track         TEXT NOT NULL,
  source        TEXT,
  source_url    TEXT,
  location      TEXT,
  comp          TEXT,
  jd_raw        TEXT NOT NULL,
  deadline      DATE,
  posted_at     DATE,
  priority      INTEGER DEFAULT 3,
  created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  fingerprint   TEXT,                      -- dedupe key across sources
  score         INTEGER,                   -- relevance, 0-100
  score_verdict TEXT,                      -- pursue | maybe | reject
  score_reasons TEXT,
  discovered_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS application (
  id             INTEGER PRIMARY KEY,
  posting_id     INTEGER NOT NULL REFERENCES posting(id) ON DELETE CASCADE,
  status         TEXT NOT NULL DEFAULT 'draft',
  resume_variant TEXT,
  letter_path    TEXT,
  resume_path    TEXT,
  fieldpack_path TEXT,
  reviewed_at    TIMESTAMP,
  submitted_at   TIMESTAMP,
  notes          TEXT
);

CREATE TABLE IF NOT EXISTS event (
  id             INTEGER PRIMARY KEY,
  application_id INTEGER REFERENCES application(id) ON DELETE CASCADE,
  kind           TEXT NOT NULL,
  occurred_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  detail         TEXT
);

-- Reserved by the original data model; nothing reads or writes it yet.
CREATE TABLE IF NOT EXISTS contact (
  id         INTEGER PRIMARY KEY,
  posting_id INTEGER REFERENCES posting(id) ON DELETE SET NULL,
  name       TEXT, title TEXT, email TEXT, linkedin TEXT,
  last_touch DATE, notes TEXT
);

CREATE TABLE IF NOT EXISTS followup (
  id             INTEGER PRIMARY KEY,
  application_id INTEGER REFERENCES application(id) ON DELETE CASCADE,
  due_on         DATE NOT NULL,
  action         TEXT NOT NULL,
  done           INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_posting_deadline ON posting(deadline);
CREATE UNIQUE INDEX IF NOT EXISTS idx_posting_fingerprint
  ON posting(fingerprint) WHERE fingerprint IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_application_status ON application(status);
CREATE INDEX IF NOT EXISTS idx_event_app ON event(application_id, occurred_at);
"""


def db_path() -> Path:
    return data_dir() / "apply.db"


#: Databases already brought up to date in this process. Migration is cheap but
#: not free, and connect() is called often enough for that to matter.
_MIGRATED: set[str] = set()


def connect(path: Path | None = None, *, migrate_on_open: bool = True) -> sqlite3.Connection:
    path = path or db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # An apply.db written by an earlier version is missing the discovery columns,
    # and the first query against one fails with "no such column". Bring it up to
    # date on open rather than making every caller remember to.
    key = str(path.resolve())
    if migrate_on_open and key not in _MIGRATED:
        try:
            if conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='posting'"
            ).fetchone():
                migrate(conn)
        except sqlite3.Error:
            pass                                 # a brand-new file; init_db handles it
        _MIGRATED.add(key)
    return conn


#: Columns added after the first release. Applied in order, idempotently, so an
#: existing apply.db keeps its rows across an upgrade.
MIGRATIONS = [
    ("posting", "fingerprint", "TEXT"),
    ("posting", "score", "INTEGER"),
    ("posting", "score_verdict", "TEXT"),
    ("posting", "score_reasons", "TEXT"),
    ("posting", "discovered_at", "TIMESTAMP"),
]


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Add any column this version expects and an older database lacks."""
    applied = []
    for table, column, kind in MIGRATIONS:
        existing = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            with conn:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")
            applied.append(f"{table}.{column}")
    with conn:
        conn.execute("""CREATE UNIQUE INDEX IF NOT EXISTS idx_posting_fingerprint
                        ON posting(fingerprint) WHERE fingerprint IS NOT NULL""")
    return applied


def init_db(path: Path | None = None) -> Path:
    path = path or db_path()
    conn = connect(path)
    with conn:
        conn.executescript(SCHEMA)
    migrate(conn)
    conn.close()
    return path


def _now() -> str:
    return _dt.datetime.now().replace(microsecond=0).isoformat(sep=" ")


def _as_date(value) -> _dt.date | None:
    if value is None or value == "":
        return None
    if isinstance(value, _dt.date):
        return value
    return _dt.date.fromisoformat(str(value)[:10])


def _date_str(value) -> str | None:
    d = _as_date(value)
    return d.isoformat() if d else None


# ---------------------------------------------------------------- postings


def create_posting(conn: sqlite3.Connection, p: Posting) -> Posting:
    with conn:
        cur = conn.execute(
            """INSERT INTO posting
               (slug, company, role, track, source, source_url, location, comp,
                jd_raw, deadline, posted_at, priority, fingerprint, score,
                score_verdict, score_reasons, discovered_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                p.slug, p.company, p.role, p.track, p.source, p.source_url,
                p.location, p.comp, p.jd_raw, _date_str(p.deadline),
                _date_str(p.posted_at), p.priority, p.fingerprint, p.score,
                p.score_verdict, p.score_reasons, p.discovered_at,
            ),
        )
        p.id = cur.lastrowid
        app_cur = conn.execute(
            "INSERT INTO application (posting_id, status) VALUES (?, ?)",
            (p.id, Status.DRAFT.value),
        )
        conn.execute(
            "INSERT INTO event (application_id, kind, occurred_at, detail) VALUES (?,?,?,?)",
            (app_cur.lastrowid, EventKind.CREATED.value, _now(),
             f"{p.company} — {p.role} ({p.track})"),
        )
    return p


def _posting_from_row(r: sqlite3.Row) -> Posting:
    return Posting(
        id=r["id"], slug=r["slug"], company=r["company"], role=r["role"],
        track=r["track"], source=r["source"], source_url=r["source_url"],
        location=r["location"], comp=r["comp"], jd_raw=r["jd_raw"],
        deadline=_as_date(r["deadline"]), posted_at=_as_date(r["posted_at"]),
        priority=r["priority"], created_at=r["created_at"],
        fingerprint=_get(r, "fingerprint"), score=_get(r, "score"),
        score_verdict=_get(r, "score_verdict"), score_reasons=_get(r, "score_reasons"),
        discovered_at=_get(r, "discovered_at"),
    )


def _get(row: sqlite3.Row, key: str):
    """Tolerate a row from a database that predates a column."""
    try:
        return row[key]
    except (IndexError, KeyError):
        return None


def _application_from_row(r: sqlite3.Row) -> Application:
    return Application(
        id=r["id"], posting_id=r["posting_id"], status=r["status"],
        resume_variant=r["resume_variant"], letter_path=r["letter_path"],
        resume_path=r["resume_path"], fieldpack_path=r["fieldpack_path"],
        reviewed_at=r["reviewed_at"], submitted_at=r["submitted_at"],
        notes=r["notes"],
    )


def fingerprint_exists(conn: sqlite3.Connection, fingerprint: str) -> bool:
    """Whether this role has already been seen, from any source."""
    return conn.execute(
        "SELECT 1 FROM posting WHERE fingerprint = ? LIMIT 1", (fingerprint,)
    ).fetchone() is not None


def get_posting(conn: sqlite3.Connection, slug: str) -> Posting | None:
    r = conn.execute("SELECT * FROM posting WHERE slug = ?", (slug,)).fetchone()
    return _posting_from_row(r) if r else None


def get_posting_by_id(conn: sqlite3.Connection, pid: int) -> Posting | None:
    r = conn.execute("SELECT * FROM posting WHERE id = ?", (pid,)).fetchone()
    return _posting_from_row(r) if r else None


def update_posting(conn: sqlite3.Connection, p: Posting) -> None:
    with conn:
        conn.execute(
            """UPDATE posting SET company=?, role=?, track=?, source=?, source_url=?,
               location=?, comp=?, deadline=?, posted_at=?, priority=? WHERE id=?""",
            (p.company, p.role, p.track, p.source, p.source_url, p.location,
             p.comp, _date_str(p.deadline), _date_str(p.posted_at), p.priority, p.id),
        )


def update_description(conn: sqlite3.Connection, p: Posting) -> None:
    """Store a posting's fuller text and whatever re-scoring it produced.

    Separate from update_posting on purpose: jd_raw is only ever written here,
    and only by `apply describe`, which appends to it rather than replacing
    source text.
    """
    with conn:
        conn.execute(
            """UPDATE posting SET jd_raw=?, track=?, location=?, comp=?, deadline=?,
               score=?, score_verdict=?, score_reasons=? WHERE id=?""",
            (p.jd_raw, p.track, p.location, p.comp, _date_str(p.deadline),
             p.score, p.score_verdict, p.score_reasons, p.id),
        )


def update_score(conn: sqlite3.Connection, p: Posting) -> None:
    """The gate's verdict and nothing else. Used by `apply rescore`."""
    with conn:
        conn.execute(
            "UPDATE posting SET score=?, score_verdict=?, score_reasons=? WHERE id=?",
            (p.score, p.score_verdict, p.score_reasons, p.id),
        )


def delete_posting(conn: sqlite3.Connection, slug: str) -> bool:
    with conn:
        cur = conn.execute("DELETE FROM posting WHERE slug = ?", (slug,))
    return cur.rowcount > 0


# ------------------------------------------------------------ applications


def get_application(conn: sqlite3.Connection, posting_id: int) -> Application | None:
    r = conn.execute(
        "SELECT * FROM application WHERE posting_id = ?", (posting_id,)
    ).fetchone()
    return _application_from_row(r) if r else None


def get_application_by_id(conn: sqlite3.Connection, app_id: int) -> Application | None:
    r = conn.execute("SELECT * FROM application WHERE id = ?", (app_id,)).fetchone()
    return _application_from_row(r) if r else None


def set_documents(
    conn: sqlite3.Connection,
    app_id: int,
    *,
    resume_variant: str | None = None,
    letter_path: str | None = None,
    resume_path: str | None = None,
    fieldpack_path: str | None = None,
) -> None:
    with conn:
        conn.execute(
            """UPDATE application SET resume_variant=?, letter_path=?, resume_path=?,
               fieldpack_path=? WHERE id=?""",
            (resume_variant, letter_path, resume_path, fieldpack_path, app_id),
        )


#: Which event a status change writes into the log.
_EVENT_FOR: dict[Status, EventKind] = {
    Status.GENERATED: EventKind.GENERATED,
    Status.READY: EventKind.REVIEWED,
    Status.SUBMITTED: EventKind.SUBMITTED,
    Status.ACKNOWLEDGED: EventKind.ACK,
    Status.ASSESSMENT: EventKind.OA_RECEIVED,
    Status.INTERVIEWING: EventKind.INTERVIEW,
    Status.OFFER: EventKind.OFFER,
    Status.REJECTED: EventKind.REJECT,
    Status.WITHDRAWN: EventKind.WITHDRAWN,
}


def transition(
    conn: sqlite3.Connection,
    app_id: int,
    target: Status,
    *,
    via: str,
    detail: str | None = None,
) -> Application:
    """The only way the status column changes.

    `via` names the action asking for the change. Statuses in HUMAN_GATED refuse
    every `via` but their own, so no side effect anywhere else in the codebase can
    mark an application reviewed or submitted.
    """
    app = get_application_by_id(conn, app_id)
    if app is None:
        raise LookupError(f"no application {app_id}")
    current = Status(app.status)
    check_transition(current, target, via)

    now = _now()
    sets = ["status = ?"]
    params: list = [target.value]

    if target is Status.READY:
        sets.append("reviewed_at = ?")
        params.append(now)
    elif target is Status.GENERATED:
        # A re-write invalidates the read that came before it.
        sets.append("reviewed_at = NULL")
    if target is Status.SUBMITTED:
        sets.append("submitted_at = ?")
        params.append(now)

    params.append(app_id)
    with conn:
        conn.execute(f"UPDATE application SET {', '.join(sets)} WHERE id = ?", params)
        kind = _EVENT_FOR.get(target, EventKind.NOTE)
        conn.execute(
            "INSERT INTO event (application_id, kind, occurred_at, detail) VALUES (?,?,?,?)",
            (app_id, kind.value, now, detail or f"{current.value} → {target.value}"),
        )
    return get_application_by_id(conn, app_id)


# ------------------------------------------------------------------ events


def add_event(
    conn: sqlite3.Connection, app_id: int, kind: EventKind | str, detail: str | None = None
) -> None:
    k = kind.value if isinstance(kind, EventKind) else str(kind)
    with conn:
        conn.execute(
            "INSERT INTO event (application_id, kind, occurred_at, detail) VALUES (?,?,?,?)",
            (app_id, k, _now(), detail),
        )


def events(conn: sqlite3.Connection, app_id: int) -> list[Event]:
    rows = conn.execute(
        "SELECT * FROM event WHERE application_id = ? ORDER BY occurred_at DESC, id DESC",
        (app_id,),
    ).fetchall()
    return [
        Event(id=r["id"], application_id=r["application_id"], kind=r["kind"],
              occurred_at=r["occurred_at"], detail=r["detail"])
        for r in rows
    ]


# --------------------------------------------------------------- followups


def add_followup(
    conn: sqlite3.Connection, app_id: int, due_on: _dt.date | str, action: str
) -> int:
    with conn:
        cur = conn.execute(
            "INSERT INTO followup (application_id, due_on, action) VALUES (?,?,?)",
            (app_id, _date_str(due_on), action),
        )
    return cur.lastrowid


def followups(
    conn: sqlite3.Connection, app_id: int | None = None, include_done: bool = False
) -> list[Followup]:
    sql = "SELECT * FROM followup"
    where, params = [], []
    if app_id is not None:
        where.append("application_id = ?")
        params.append(app_id)
    if not include_done:
        where.append("done = 0")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY due_on ASC, id ASC"
    return [
        Followup(id=r["id"], application_id=r["application_id"],
                 due_on=_as_date(r["due_on"]), action=r["action"], done=bool(r["done"]))
        for r in conn.execute(sql, params).fetchall()
    ]


def complete_followup(conn: sqlite3.Connection, followup_id: int) -> None:
    with conn:
        conn.execute("UPDATE followup SET done = 1 WHERE id = ?", (followup_id,))


# ---------------------------------------------------------------- contacts


# -------------------------------------------------------------- pipeline


def rows(conn: sqlite3.Connection, statuses: Iterable[str] | None = None) -> list[Row]:
    """Every posting joined to its application, deadline ascending, nulls last."""
    sql = """
        SELECT p.*, a.id AS app_id, a.posting_id, a.status, a.resume_variant,
               a.letter_path, a.resume_path, a.fieldpack_path, a.reviewed_at,
               a.submitted_at, a.notes
        FROM posting p JOIN application a ON a.posting_id = p.id
    """
    params: list = []
    if statuses:
        statuses = list(statuses)
        sql += " WHERE a.status IN (%s)" % ",".join("?" * len(statuses))
        params += statuses
    sql += " ORDER BY (p.deadline IS NULL), p.deadline ASC, p.priority ASC, p.id ASC"

    out: list[Row] = []
    for r in conn.execute(sql, params).fetchall():
        posting = _posting_from_row(r)
        app = Application(
            id=r["app_id"], posting_id=r["posting_id"], status=r["status"],
            resume_variant=r["resume_variant"], letter_path=r["letter_path"],
            resume_path=r["resume_path"], fieldpack_path=r["fieldpack_path"],
            reviewed_at=r["reviewed_at"], submitted_at=r["submitted_at"], notes=r["notes"],
        )
        out.append(Row(posting=posting, application=app,
                       followups=followups(conn, app.id)))
    return out


def row_for(conn: sqlite3.Connection, slug: str) -> Row | None:
    for r in rows(conn):
        if r.posting.slug == slug:
            return r
    return None
