"""API data transfer objects. The OpenAPI schema FastAPI derives from these is what the
React client's types are generated from, so keep them explicit and well named."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from leadagent.models import (
    APIModel,
    Booking,
    ConsentStatus,
    Lead,
    LeadSource,
    Message,
    Notification,
    Score,
    Tier,
    ToolCall,
)

LeadStatus = Literal[
    "new", "in_progress", "booked", "escalated", "closed", "spam", "opted_out", "human"
]

EventType = Literal[
    "lead_created",
    "message",
    "deferred",
    "tool_call",
    "state",
    "notification",
    "first_response",
    "turn_done",
    "error",
]


# ------------------------------------------------------------------- requests
class LeadIn(BaseModel):
    """A lead from a web form, missed call or inbound text."""

    company: str | None = Field(
        default=None, description="Company slug. Defaults to the active one."
    )
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    message: str = ""
    source: LeadSource = "web_form"
    consent: bool | None = Field(
        default=None, description="Explicit SMS consent captured by the form, if any."
    )

    @model_validator(mode="after")
    def _reachable(self) -> LeadIn:
        if self.source in ("text", "missed_call") and not self.phone:
            raise ValueError(f"a phone number is required for source '{self.source}'")
        if not (self.phone or self.email):
            raise ValueError("provide a phone number or an email address")
        if self.source == "text" and not self.message.strip():
            raise ValueError("a text lead needs a message")
        return self


class InboundMessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class HumanMessageIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class WebFormWebhook(BaseModel):
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    message: str = ""
    consent: bool | None = None


class MissedCallWebhook(BaseModel):
    from_number: str = Field(alias="from")
    name: str | None = None


class SmsWebhook(BaseModel):
    from_number: str = Field(alias="from")
    body: str
    name: str | None = None


class ClockIn(BaseModel):
    now: datetime | None = Field(
        default=None, description="Simulated 'now' (ISO 8601 with offset). Null restores real time."
    )
    preset: Literal["business_hours", "after_hours", "real"] | None = Field(
        default=None,
        description="Shortcut resolved in the company's timezone: 10:00 or 22:30 on the next "
        "weekday, or real time. Overrides `now`.",
    )
    company: str | None = Field(default=None, description="Company whose timezone a preset uses.")


class ClockOut(APIModel):
    now: datetime
    simulated: bool


# ------------------------------------------------------------------ responses
class Accepted(APIModel):
    lead_id: str
    created_at: datetime
    status: Literal["processing"] = "processing"


class OfficeBrief(APIModel):
    id: str
    name: str
    reps: int


class QualificationFieldView(APIModel):
    key: str
    question: str
    type: str
    options: list[str] = Field(default_factory=list)


class CompanyBrief(APIModel):
    slug: str
    name: str
    brand_color: str
    logo_url: str


class CompanyList(APIModel):
    default: str
    companies: list[CompanyBrief]


class CompanyPublicConfig(APIModel):
    """Everything the UI needs to brand itself. Loaded at runtime, never hardcoded."""

    slug: str
    name: str
    description: str
    brand_color: str
    logo_url: str
    timezone: str
    tone: str
    reply_signature: str
    hot_lead_threshold: int
    warm_lead_threshold: int
    appointment_kind: str
    appointment_minutes: int
    fields: list[QualificationFieldView]
    offices: list[OfficeBrief]
    slack_channel: str
    crm_pipeline: str


class LeadSummary(APIModel):
    id: str
    company: str
    name: str | None
    phone: str | None
    source: LeadSource
    created_at: datetime
    status: LeadStatus
    score: int | None
    tier: Tier | None
    first_response_seconds: float | None
    consent: ConsentStatus
    booked: bool
    escalated: bool


class RoutingView(APIModel):
    office_id: str | None
    office_name: str | None
    rep_id: str | None
    rep_name: str | None
    reason: str | None


class CRMPreview(APIModel):
    contact_id: str | None
    pipeline: str
    stage: str | None
    synced: bool
    properties: dict[str, Any]


class DeferredView(APIModel):
    body: str
    deliver_after: datetime


class LeadDetail(APIModel):
    summary: LeadSummary
    lead: Lead
    messages: list[Message]
    answers: dict[str, Any]
    missing_fields: list[str]
    score: Score | None
    routing: RoutingView
    booking: Booking | None
    crm: CRMPreview
    notifications: list[Notification]
    tool_calls: list[ToolCall]
    flags: list[str]
    events: list[dict[str, Any]]
    deferred: list[DeferredView]


class LeadList(APIModel):
    leads: list[LeadSummary]


class StreamEvent(APIModel):
    """One server-sent event. `id` is the replay cursor (Last-Event-ID)."""

    id: int
    type: EventType
    lead_id: str
    company: str
    at: datetime
    data: dict[str, Any]


class EventHistory(APIModel):
    events: list[StreamEvent]


class Health(APIModel):
    ok: bool
    llm: Literal["ready", "missing_api_key"]
    model: str
    adapters: dict[str, str]
    simulated_clock: bool


class ScenarioBrief(APIModel):
    id: str
    title: str
    description: str
    company: str
    source: LeadSource
    followups: int
    clock: datetime | None


class ScenarioList(APIModel):
    scenarios: list[ScenarioBrief]
