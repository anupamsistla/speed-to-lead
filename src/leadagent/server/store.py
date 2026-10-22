"""SQLite persistence for leads, messages, tool calls, scores, notifications, events, turns.

The full LeadSession is stored as JSON (so a restart restores a conversation exactly) next to
queryable tables. One connection guarded by a lock is plenty for a single-process demo; the
interface is small so Postgres can replace it later.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from leadagent.models import Notification, ToolCall
from leadagent.session import LeadSession

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
  id TEXT PRIMARY KEY, company TEXT NOT NULL, phone_digits TEXT, name TEXT, source TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, first_response_seconds REAL,
  score INTEGER, tier TEXT, consent TEXT, deferred_count INTEGER NOT NULL DEFAULT 0,
  session_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS leads_company ON leads(company, created_at);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY, lead_id TEXT NOT NULL, direction TEXT NOT NULL, body TEXT NOT NULL,
  created_at TEXT NOT NULL, sent INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_lead ON messages(lead_id, created_at);
CREATE TABLE IF NOT EXISTS tool_calls (
  id TEXT PRIMARY KEY, lead_id TEXT NOT NULL, name TEXT NOT NULL, args TEXT NOT NULL,
  result TEXT NOT NULL, latency_ms REAL NOT NULL, started_at TEXT NOT NULL, error INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS tool_calls_lead ON tool_calls(lead_id, started_at);
CREATE TABLE IF NOT EXISTS scores (
  id INTEGER PRIMARY KEY AUTOINCREMENT, lead_id TEXT NOT NULL, score INTEGER NOT NULL,
  tier TEXT NOT NULL, breakdown TEXT NOT NULL, at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS notifications (
  id INTEGER PRIMARY KEY AUTOINCREMENT, lead_id TEXT NOT NULL, payload TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT, lead_id TEXT NOT NULL, company TEXT NOT NULL,
  type TEXT NOT NULL, data TEXT NOT NULL, at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS events_lead ON events(lead_id, id);
CREATE TABLE IF NOT EXISTS turns (
  id INTEGER PRIMARY KEY AUTOINCREMENT, lead_id TEXT NOT NULL, trigger TEXT NOT NULL,
  started_at TEXT NOT NULL, finished_at TEXT NOT NULL, duration_ms REAL NOT NULL
);
"""


def phone_digits(phone: str | None) -> str | None:
    if not phone:
        return None
    d = re.sub(r"\D", "", phone)
    return d[-10:] if d else None


class Store:
    def __init__(self, path: str | Path = ":memory:"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        with self._lock:
            if self.path != ":memory:":
                self.db.execute("PRAGMA journal_mode=WAL")
            self.db.executescript(SCHEMA)

    # ---------------------------------------------------------------- sessions
    def save_session(self, company: str, session: LeadSession, now: datetime) -> None:
        lead, score = session.lead, session.score
        with self._lock:
            self.db.execute(
                """INSERT INTO leads (id, company, phone_digits, name, source, created_at,
                     updated_at, first_response_seconds, score, tier, consent, deferred_count,
                     session_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET phone_digits=excluded.phone_digits,
                     name=excluded.name, updated_at=excluded.updated_at,
                     first_response_seconds=excluded.first_response_seconds,
                     score=excluded.score, tier=excluded.tier, consent=excluded.consent,
                     deferred_count=excluded.deferred_count, session_json=excluded.session_json""",
                (
                    lead.id,
                    company,
                    phone_digits(lead.phone),
                    lead.name,
                    lead.source,
                    lead.created_at.isoformat(),
                    now.isoformat(),
                    session.first_response_seconds,
                    score.score if score else None,
                    score.tier if score else None,
                    session.consent,
                    len(session.deferred),
                    session.model_dump_json(),
                ),
            )
            for m in session.messages:
                self.db.execute(
                    "INSERT INTO messages VALUES (?,?,?,?,?,?) "
                    "ON CONFLICT(id) DO UPDATE SET sent=excluded.sent",
                    (m.id, m.lead_id, m.direction, m.body, m.created_at.isoformat(), int(m.sent)),
                )
            if score:
                last = self.db.execute(
                    "SELECT score, tier, breakdown FROM scores WHERE lead_id=? ORDER BY id DESC",
                    (lead.id,),
                ).fetchone()
                breakdown = json.dumps([i.model_dump() for i in score.breakdown])
                if not last or (last["score"], last["tier"], last["breakdown"]) != (
                    score.score,
                    score.tier,
                    breakdown,
                ):
                    self.db.execute(
                        "INSERT INTO scores (lead_id, score, tier, breakdown, at) "
                        "VALUES (?,?,?,?,?)",
                        (lead.id, score.score, score.tier, breakdown, now.isoformat()),
                    )
            self.db.commit()

    def load_session(self, lead_id: str) -> tuple[str, LeadSession] | None:
        with self._lock:
            r = self.db.execute(
                "SELECT company, session_json FROM leads WHERE id=?", (lead_id,)
            ).fetchone()
        if r is None:
            return None
        return r["company"], LeadSession.model_validate_json(r["session_json"])

    def list_leads(self, company: str | None = None, limit: int = 100) -> list[str]:
        sql, args = "SELECT id FROM leads", []
        if company:
            sql += " WHERE company=?"
            args.append(company)
        sql += " ORDER BY created_at DESC LIMIT ?"
        args.append(limit)
        with self._lock:
            return [r["id"] for r in self.db.execute(sql, args)]

    def find_lead_by_phone(self, company: str, phone: str) -> str | None:
        digits = phone_digits(phone)
        if not digits:
            return None
        with self._lock:
            r = self.db.execute(
                "SELECT id FROM leads WHERE company=? AND phone_digits=? "
                "ORDER BY created_at DESC LIMIT 1",
                (company, digits),
            ).fetchone()
        return r["id"] if r else None

    def lead_row(self, lead_id: str) -> dict[str, Any] | None:
        with self._lock:
            r = self.db.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
        return dict(r) if r else None

    def leads_with_deferred(self, company: str) -> list[str]:
        with self._lock:
            rows = self.db.execute(
                "SELECT id FROM leads WHERE company=? AND deferred_count > 0", (company,)
            ).fetchall()
        return [r["id"] for r in rows]

    # -------------------------------------------------------------- tool calls
    def add_tool_call(self, tc: ToolCall) -> None:
        with self._lock:
            self.db.execute(
                "INSERT OR REPLACE INTO tool_calls VALUES (?,?,?,?,?,?,?,?)",
                (
                    tc.id,
                    tc.lead_id,
                    tc.name,
                    json.dumps(tc.args, default=str),
                    json.dumps(tc.result, default=str),
                    tc.latency_ms,
                    tc.started_at.isoformat(),
                    int(tc.error),
                ),
            )
            self.db.commit()

    def tool_calls(self, lead_id: str) -> list[ToolCall]:
        with self._lock:
            rows = self.db.execute(
                "SELECT * FROM tool_calls WHERE lead_id=? ORDER BY started_at, rowid", (lead_id,)
            ).fetchall()
        return [
            ToolCall(
                id=r["id"],
                lead_id=r["lead_id"],
                name=r["name"],
                args=json.loads(r["args"]),
                result=json.loads(r["result"]),
                latency_ms=r["latency_ms"],
                started_at=datetime.fromisoformat(r["started_at"]),
                error=bool(r["error"]),
            )
            for r in rows
        ]

    def score_history(self, lead_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self.db.execute(
                "SELECT score, tier, breakdown, at FROM scores WHERE lead_id=? ORDER BY id",
                (lead_id,),
            ).fetchall()
        return [
            {
                "score": r["score"],
                "tier": r["tier"],
                "breakdown": json.loads(r["breakdown"]),
                "at": r["at"],
            }
            for r in rows
        ]

    # ------------------------------------------------------------ notifications
    def add_notification(self, n: Notification) -> None:
        with self._lock:
            self.db.execute(
                "INSERT INTO notifications (lead_id, payload, created_at) VALUES (?,?,?)",
                (n.lead_id, n.model_dump_json(), n.created_at.isoformat()),
            )
            self.db.commit()

    def notifications(self, lead_id: str) -> list[Notification]:
        with self._lock:
            rows = self.db.execute(
                "SELECT payload FROM notifications WHERE lead_id=? ORDER BY id", (lead_id,)
            ).fetchall()
        return [Notification.model_validate_json(r["payload"]) for r in rows]

    # -------------------------------------------------------------------- events
    def add_event(
        self, lead_id: str, company: str, type_: str, data: dict[str, Any], at: datetime
    ) -> int:
        with self._lock:
            cur = self.db.execute(
                "INSERT INTO events (lead_id, company, type, data, at) VALUES (?,?,?,?,?)",
                (lead_id, company, type_, json.dumps(data, default=str), at.isoformat()),
            )
            self.db.commit()
            return int(cur.lastrowid or 0)

    def events(
        self,
        *,
        lead_id: str | None = None,
        company: str | None = None,
        after: int = 0,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM events WHERE id > ?", [after]
        if lead_id:
            sql += " AND lead_id=?"
            args.append(lead_id)
        if company:
            sql += " AND company=?"
            args.append(company)
        sql += " ORDER BY id LIMIT ?"
        args.append(limit)
        with self._lock:
            rows = self.db.execute(sql, args).fetchall()
        return [{**dict(r), "data": json.loads(r["data"])} for r in rows]

    # --------------------------------------------------------------------- turns
    def add_turn(
        self, lead_id: str, trigger: str, started_at: datetime, finished_at: datetime, ms: float
    ) -> None:
        with self._lock:
            self.db.execute(
                "INSERT INTO turns (lead_id, trigger, started_at, finished_at, duration_ms) "
                "VALUES (?,?,?,?,?)",
                (lead_id, trigger, started_at.isoformat(), finished_at.isoformat(), ms),
            )
            self.db.commit()

    def turns(self, lead_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [
                dict(r)
                for r in self.db.execute(
                    "SELECT * FROM turns WHERE lead_id=? ORDER BY id", (lead_id,)
                )
            ]
