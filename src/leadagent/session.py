"""Mutable per-lead state shared by tools and the agent loop. Persisted in phase 4."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from leadagent.models import Booking, ConsentStatus, Lead, Message, Score, Slot


class DeferredMessage(BaseModel):
    body: str
    deliver_after: datetime


class LeadSession(BaseModel):
    lead: Lead
    fields: dict[str, Any] = Field(default_factory=dict)
    score: Score | None = None
    office_id: str | None = None
    rep_id: str | None = None
    booking: Booking | None = None
    offered_slots: dict[str, Slot] = Field(default_factory=dict)
    consent: ConsentStatus = "unknown"
    escalated: bool = False
    escalation_reason: str | None = None
    human_takeover: bool = False  # a person has taken over; the agent must stay silent
    flags: list[str] = Field(default_factory=list)
    kb_misses: int = 0
    crm_contact_id: str | None = None
    messages: list[Message] = Field(default_factory=list)
    deferred: list[DeferredMessage] = Field(default_factory=list)
    first_response_seconds: float | None = None
    closed_reason: str | None = None  # set when disqualified or out of area

    def add_flag(self, flag: str) -> None:
        if flag not in self.flags:
            self.flags.append(flag)

    def values(self) -> dict[str, Any]:
        """Qualification fields plus contact fields, as seen by scoring conditions."""
        out = dict(self.fields)
        for k in ("name", "phone", "email", "source"):
            v = getattr(self.lead, k)
            if v:
                out.setdefault(k, v)
        return out
