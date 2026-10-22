"""Mock adapters. The whole demo runs on these with no external services."""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from leadagent.clock import Clock, SystemClock
from leadagent.config.schemas import WEEKDAYS, BusinessHours
from leadagent.models import Booking, CRMContact, Lead, Message, Notification, Slot


class MockChannel:
    """A simulated SMS/chat thread. The UI reads `outbox`; phase 4 also publishes events."""

    def __init__(self, clock: Clock | None = None):
        self.clock = clock or SystemClock()
        self.outbox: list[Message] = []

    def send(self, lead: Lead, body: str) -> Message:
        msg = Message(
            id=uuid.uuid4().hex[:12],
            lead_id=lead.id,
            direction="outbound",
            body=body,
            created_at=self.clock.now(),
        )
        self.outbox.append(msg)
        return msg


def _digits(phone: str | None) -> str | None:
    if not phone:
        return None
    d = re.sub(r"\D", "", phone)
    return d[-10:] if d else None


class MockCRM:
    """Local tables in SQLite (in memory by default)."""

    def __init__(self, path: str = ":memory:", table: str = "crm_contacts"):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table):
            raise ValueError(f"bad table name {table!r}")
        self.table = table
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            f"""CREATE TABLE IF NOT EXISTS {table} (
                 id TEXT PRIMARY KEY, name TEXT, phone TEXT, email TEXT,
                 properties TEXT NOT NULL DEFAULT '{{}}', pipeline TEXT, stage TEXT)"""
        )

    @staticmethod
    def _row(r: sqlite3.Row) -> CRMContact:
        return CRMContact(
            id=r["id"],
            name=r["name"],
            phone=r["phone"],
            email=r["email"],
            properties=json.loads(r["properties"]),
            pipeline=r["pipeline"],
            stage=r["stage"],
        )

    def find_contact(self, *, phone: str | None, email: str | None) -> CRMContact | None:
        if email:
            r = self.db.execute(
                f"SELECT * FROM {self.table} WHERE lower(email)=lower(?)", (email,)
            ).fetchone()
            if r:
                return self._row(r)
        digits = _digits(phone)
        if digits:
            for r in self.db.execute(f"SELECT * FROM {self.table} WHERE phone IS NOT NULL"):
                if _digits(r["phone"]) == digits:
                    return self._row(r)
        return None

    def upsert_contact(
        self,
        *,
        name: str | None,
        phone: str | None,
        email: str | None,
        properties: dict[str, Any],
        pipeline: str,
        stage: str,
    ) -> CRMContact:
        existing = self.find_contact(phone=phone, email=email)
        if existing:
            merged = {**existing.properties, **properties}
            self.db.execute(
                f"UPDATE {self.table} SET name=?, phone=?, email=?, properties=?, pipeline=?, "
                "stage=? WHERE id=?",
                (
                    name or existing.name,
                    phone or existing.phone,
                    email or existing.email,
                    json.dumps(merged, default=str),
                    pipeline,
                    stage,
                    existing.id,
                ),
            )
            contact_id = existing.id
        else:
            contact_id = f"crm_{uuid.uuid4().hex[:8]}"
            self.db.execute(
                f"INSERT INTO {self.table} VALUES (?,?,?,?,?,?,?)",
                (
                    contact_id,
                    name,
                    phone,
                    email,
                    json.dumps(properties, default=str),
                    pipeline,
                    stage,
                ),
            )
        self.db.commit()
        return self.get(contact_id)

    def update_stage(self, contact_id: str, *, pipeline: str, stage: str) -> None:
        cur = self.db.execute(
            f"UPDATE {self.table} SET pipeline=?, stage=? WHERE id=?", (pipeline, stage, contact_id)
        )
        if cur.rowcount == 0:
            raise KeyError(f"no CRM contact {contact_id}")
        self.db.commit()

    def get(self, contact_id: str) -> CRMContact:
        r = self.db.execute(f"SELECT * FROM {self.table} WHERE id=?", (contact_id,)).fetchone()
        if r is None:
            raise KeyError(contact_id)
        return self._row(r)

    def seed_contact(self, **kwargs: Any) -> CRMContact:
        """Test and demo helper: pre-existing CRM record."""
        kwargs.setdefault("properties", {})
        kwargs.setdefault("pipeline", "Residential Sales")
        kwargs.setdefault("stage", "New Lead")
        kwargs.setdefault("name", None)
        kwargs.setdefault("phone", None)
        kwargs.setdefault("email", None)
        return self.upsert_contact(**kwargs)


class MockCalendar:
    """Availability generated from each rep's business hours, minus existing bookings."""

    STEP_MINUTES = 30

    def __init__(
        self, rep_hours: dict[str, BusinessHours], timezone: str, clock: Clock | None = None
    ):
        self.rep_hours = rep_hours
        self.tz = ZoneInfo(timezone)
        self.clock = clock or SystemClock()
        self.bookings: dict[str, list[Booking]] = {r: [] for r in rep_hours}
        self._lock = threading.Lock()  # two leads must never take the same slot

    def _busy(self, rep_id: str, start: datetime, end: datetime) -> bool:
        return any(b.start < end and start < b.end for b in self.bookings[rep_id])

    def _within_hours(self, rep_id: str, start: datetime, end: datetime) -> bool:
        s, e = start.astimezone(self.tz), end.astimezone(self.tz)
        if s.date() != e.date():
            return False
        window = self.rep_hours[rep_id].window(WEEKDAYS[s.weekday()])
        if window is None:
            return False
        ws, we = window
        return ws <= s.strftime("%H:%M") and e.strftime("%H:%M") <= we

    def is_free(self, rep_id: str, start: datetime, duration_minutes: int) -> bool:
        if rep_id not in self.rep_hours:
            return False
        end = start + timedelta(minutes=duration_minutes)
        return self._within_hours(rep_id, start, end) and not self._busy(rep_id, start, end)

    def get_slots(
        self,
        rep_ids: list[str],
        *,
        start: datetime,
        end: datetime,
        duration_minutes: int,
    ) -> list[Slot]:
        step = timedelta(minutes=self.STEP_MINUTES)
        local_start = start.astimezone(self.tz)
        # first grid point at or after `start`
        minutes = local_start.hour * 60 + local_start.minute
        bump = (-minutes) % self.STEP_MINUTES
        cur = local_start.replace(second=0, microsecond=0) + timedelta(minutes=bump)
        if cur < local_start:
            cur += step
        out: list[Slot] = []
        while cur < end:
            for rep_id in rep_ids:
                if self.is_free(rep_id, cur, duration_minutes):
                    out.append(self._slot(rep_id, cur, duration_minutes))
                    break
            cur += step
        return out

    def _slot(self, rep_id: str, start: datetime, duration_minutes: int) -> Slot:
        local = start.astimezone(self.tz)
        label = f"{local:%a %b} {local.day}, {local.strftime('%I:%M %p').lstrip('0')}"
        return Slot(
            slot_id=f"{rep_id}@{local.isoformat()}",
            rep_id=rep_id,
            start=local,
            end=local + timedelta(minutes=duration_minutes),
            label=label,
        )

    def book(
        self, *, slot: Slot, lead: Lead, office_id: str, office_name: str, rep_name: str, kind: str
    ) -> Booking:
        duration = int((slot.end - slot.start).total_seconds() // 60)
        with self._lock:
            return self._book_locked(slot, lead, office_id, office_name, rep_name, kind, duration)

    def _book_locked(
        self,
        slot: Slot,
        lead: Lead,
        office_id: str,
        office_name: str,
        rep_name: str,
        kind: str,
        duration: int,
    ) -> Booking:
        if not self.is_free(slot.rep_id, slot.start, duration):
            raise ValueError("slot is no longer available")
        booking = Booking(
            id=f"bk_{uuid.uuid4().hex[:8]}",
            lead_id=lead.id,
            rep_id=slot.rep_id,
            rep_name=rep_name,
            office_id=office_id,
            office_name=office_name,
            start=slot.start,
            end=slot.end,
            label=slot.label,
            kind=kind,
        )
        self.bookings[slot.rep_id].append(booking)
        return booking


class MockNotifier:
    """Collects notifications; the UI renders them as Slack-style cards."""

    def __init__(self) -> None:
        self.sent: list[Notification] = []

    def notify(self, notification: Notification) -> None:
        self.sent.append(notification)
