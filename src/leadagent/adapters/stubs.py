"""Clean stubs for integrations that are not wired yet. They fail loudly, never silently."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from leadagent.models import Booking, Lead, Message, Slot


class TwilioChannel:
    """Stub. Implement send() with the Twilio REST API and add an inbound webhook route."""

    def __init__(self, account_sid: str = "", auth_token: str = "", from_number: str = ""):
        self.account_sid, self.auth_token, self.from_number = account_sid, auth_token, from_number

    def send(self, lead: Lead, body: str) -> Message:
        raise NotImplementedError("TwilioChannel is a stub. Use CHANNEL_ADAPTER=mock.")


class GoogleCalendar:
    """Stub. Implement with the Google Calendar freebusy and events APIs."""

    def get_slots(
        self, rep_ids: list[str], *, start: datetime, end: datetime, duration_minutes: int
    ) -> list[Slot]:
        raise NotImplementedError("GoogleCalendar is a stub. Use CALENDAR_ADAPTER=mock.")

    def is_free(self, rep_id: str, start: datetime, duration_minutes: int) -> bool:
        raise NotImplementedError("GoogleCalendar is a stub. Use CALENDAR_ADAPTER=mock.")

    def book(self, **kwargs: Any) -> Booking:
        raise NotImplementedError("GoogleCalendar is a stub. Use CALENDAR_ADAPTER=mock.")
