"""Adapter interfaces. Everything external sits behind one of these."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from leadagent.models import Booking, CRMContact, Lead, Message, Notification, Slot


class Channel(Protocol):
    def send(self, lead: Lead, body: str) -> Message: ...


class CRM(Protocol):
    def find_contact(self, *, phone: str | None, email: str | None) -> CRMContact | None: ...

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
        """Create or update the contact (matched on email, then phone) and set its stage."""
        ...

    def update_stage(self, contact_id: str, *, pipeline: str, stage: str) -> None: ...


class Calendar(Protocol):
    def get_slots(
        self,
        rep_ids: list[str],
        *,
        start: datetime,
        end: datetime,
        duration_minutes: int,
    ) -> list[Slot]:
        """Free slots in [start, end). A start time appears once, owned by the first free rep
        in rep_ids order, so callers control assignment priority."""
        ...

    def is_free(self, rep_id: str, start: datetime, duration_minutes: int) -> bool: ...

    def book(
        self, *, slot: Slot, lead: Lead, office_id: str, office_name: str, rep_name: str, kind: str
    ) -> Booking: ...


class Notifier(Protocol):
    def notify(self, notification: Notification) -> None: ...


@dataclass
class Adapters:
    channel: Channel
    crm: CRM
    calendar: Calendar
    notifier: Notifier
