"""What the model spending is allowed to be.

A system that runs unattended and calls a paid API needs a cap it cannot talk
itself out of. This one is a ledger plus three ceilings, checked before every
call and recorded after every call:

    per_call    one request may not exceed this
    per_run     one discovery/generation pass may not exceed this
    monthly     the calendar month may not exceed this

When a ceiling would be breached the call does not happen. It is not deferred,
retried, or downgraded silently — BudgetExceeded is raised, the caller reports
it, and the run continues without that step. Running out of money should look
like a smaller overnight run, not a broken system.

The estimate is deliberately pessimistic: a call is checked against what it
might cost, and recorded at what it did cost.
"""

from __future__ import annotations

import datetime as _dt
import sqlite3
from dataclasses import dataclass

from . import db

SCHEMA = """
CREATE TABLE IF NOT EXISTS spend (
  id            INTEGER PRIMARY KEY,
  occurred_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  run_id        TEXT,
  purpose       TEXT NOT NULL,        -- score|write|verify|answer|classify
  model         TEXT NOT NULL,
  slug          TEXT,
  input_tokens  INTEGER DEFAULT 0,
  output_tokens INTEGER DEFAULT 0,
  cache_reads   INTEGER DEFAULT 0,
  usd           REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_spend_month ON spend(occurred_at);
"""

#: Deliberately under the $20 of credits on hand, so a runaway month cannot
#: consume the whole balance before anyone notices.
DEFAULTS = {
    "monthly_usd": 15.00,
    "per_run_usd": 2.00,
    "per_call_usd": 0.50,
}


class BudgetExceeded(RuntimeError):
    """A ceiling would have been crossed. The message names which one."""


@dataclass(slots=True)
class Spend:
    month_to_date: float
    run_to_date: float
    monthly_cap: float
    run_cap: float
    calls: int

    @property
    def remaining(self) -> float:
        return max(0.0, self.monthly_cap - self.month_to_date)

    @property
    def fraction(self) -> float:
        return 0.0 if not self.monthly_cap else self.month_to_date / self.monthly_cap

    def __str__(self) -> str:
        return (f"${self.month_to_date:.2f} of ${self.monthly_cap:.2f} this month "
                f"({self.fraction:.0%}), ${self.remaining:.2f} left, {self.calls} calls")


class Budget:
    """One ledger per database. Cheap to construct; construct it per run."""

    def __init__(self, conn: sqlite3.Connection, caps: dict | None = None,
                 run_id: str | None = None):
        self.conn = conn
        self.caps = {**DEFAULTS, **(caps or {})}
        self.run_id = run_id or _dt.datetime.now().strftime("run-%Y%m%d-%H%M%S")
        with conn:
            conn.executescript(SCHEMA)

    # ------------------------------------------------------------ reading

    def _sum(self, where: str, params: tuple) -> tuple[float, int]:
        row = self.conn.execute(
            f"SELECT COALESCE(SUM(usd), 0), COUNT(*) FROM spend WHERE {where}", params
        ).fetchone()
        return float(row[0]), int(row[1])

    def month_to_date(self) -> float:
        start = _dt.date.today().replace(day=1).isoformat()
        return self._sum("occurred_at >= ?", (start,))[0]

    def run_to_date(self) -> float:
        return self._sum("run_id = ?", (self.run_id,))[0]

    def state(self) -> Spend:
        start = _dt.date.today().replace(day=1).isoformat()
        total, calls = self._sum("occurred_at >= ?", (start,))
        return Spend(
            month_to_date=total,
            run_to_date=self.run_to_date(),
            monthly_cap=self.caps["monthly_usd"],
            run_cap=self.caps["per_run_usd"],
            calls=calls,
        )

    # ------------------------------------------------------------ writing

    def check(self, estimated_usd: float, purpose: str = "call") -> None:
        """Raise unless a call costing roughly this much is affordable."""
        if estimated_usd > self.caps["per_call_usd"]:
            raise BudgetExceeded(
                f"{purpose}: one call estimated at ${estimated_usd:.3f} exceeds the "
                f"per-call ceiling of ${self.caps['per_call_usd']:.2f}. Lower the "
                f"effort, use a smaller model, or raise the cap in profile.private.yaml."
            )
        run = self.run_to_date()
        if run + estimated_usd > self.caps["per_run_usd"]:
            raise BudgetExceeded(
                f"{purpose}: this run has spent ${run:.2f}; another ${estimated_usd:.3f} "
                f"would cross the per-run ceiling of ${self.caps['per_run_usd']:.2f}."
            )
        month = self.month_to_date()
        if month + estimated_usd > self.caps["monthly_usd"]:
            raise BudgetExceeded(
                f"{purpose}: ${month:.2f} spent this month; another ${estimated_usd:.3f} "
                f"would cross the monthly ceiling of ${self.caps['monthly_usd']:.2f}. "
                f"Nothing further will be sent until the 1st, or until you raise the cap."
            )

    def record(self, usage, purpose: str, slug: str | None = None) -> float:
        """Write what a completed call actually cost. Returns the amount."""
        cost = float(getattr(usage, "cost", 0.0) or 0.0)
        with self.conn:
            self.conn.execute(
                """INSERT INTO spend (occurred_at, run_id, purpose, model, slug,
                                      input_tokens, output_tokens, cache_reads, usd)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (_dt.datetime.now().replace(microsecond=0).isoformat(sep=" "),
                 self.run_id, purpose, getattr(usage, "model", "unknown"), slug,
                 getattr(usage, "input_tokens", 0), getattr(usage, "output_tokens", 0),
                 getattr(usage, "cache_read_tokens", 0), cost),
            )
        return cost

    def ledger(self, limit: int = 40) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM spend ORDER BY occurred_at DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()

    def by_purpose(self) -> list[tuple[str, float, int]]:
        start = _dt.date.today().replace(day=1).isoformat()
        return [
            (r[0], float(r[1]), int(r[2]))
            for r in self.conn.execute(
                """SELECT purpose, SUM(usd), COUNT(*) FROM spend
                   WHERE occurred_at >= ? GROUP BY purpose ORDER BY SUM(usd) DESC""",
                (start,),
            ).fetchall()
        ]


def open_budget(caps: dict | None = None, run_id: str | None = None) -> Budget:
    return Budget(db.connect(), caps=caps, run_id=run_id)
