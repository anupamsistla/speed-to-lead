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
    takeover_msg_index: int | None = None  # len(messages) when a person took over
    handback_note: str | None = None  # what happened while a person had it; shown to the agent once
    flags: list[str] = Field(default_factory=list)
    kb_misses: int = 0
    crm_contact_id: str | None = None
    messages: list[Message] = Field(default_factory=list)
    deferred: list[DeferredMessage] = Field(default_factory=list)
    first_response_seconds: float | None = None
    closed_reason: str | None = None  # set when disqualified, out of area, or spam
    crm_summary: str | None = None
    crm_stage: str | None = None  # last stage_event written: "created" or "booked"
    notified_kinds: list[str] = Field(default_factory=list)
    history: list[dict[str, Any]] = Field(default_factory=list)  # LLM conversation, append-only
    events: list[dict[str, Any]] = Field(default_factory=list)  # guardrail and system events

    def add_flag(self, flag: str) -> None:
        if flag not in self.flags:
            self.flags.append(flag)

    def log_event(self, type_: str, at: datetime, **detail: Any) -> None:
        self.events.append({"type": type_, "at": at.isoformat(), **detail})

    def inbound_text(self) -> str:
        """Everything the lead has said, used to allow numbers they supplied themselves."""
        parts = [m.body for m in self.messages if m.direction == "inbound"]
        parts.append(self.lead.message)
        parts.extend(str(v) for v in self.fields.values())
        return "\n".join(p for p in parts if p)

    def values(self) -> dict[str, Any]:
        """Qualification fields plus contact fields, as seen by scoring conditions."""
        out = dict(self.fields)
        for k in ("name", "phone", "email", "source"):
            v = getattr(self.lead, k)
            if v:
                out.setdefault(k, v)
        return out
