"""Shared domain models. Mirrored by web/src/types.ts."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class APIModel(BaseModel):
    """Base for models that appear in API responses: defaulted fields are always sent, so the
    generated client types mark them required."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


LeadSource = Literal["web_form", "missed_call", "text"]
ConsentStatus = Literal["unknown", "opted_in", "opted_out"]
Tier = Literal["hot", "warm", "cold", "disqualified"]


class Lead(APIModel):
    id: str
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    source: LeadSource = "web_form"
    message: str = ""
    created_at: datetime


class Message(APIModel):
    id: str
    lead_id: str
    direction: Literal["inbound", "outbound"]
    body: str
    created_at: datetime
    sent: bool = True  # False when an outbound message was deferred or blocked
    sender: Literal["lead", "agent", "human"] = "agent"


class ToolCall(APIModel):
    id: str
    lead_id: str
    name: str
    args: dict[str, Any]
    result: dict[str, Any]
    latency_ms: float
    started_at: datetime
    error: bool = False


class ScoreItem(APIModel):
    rule: str
    points: int


class Score(APIModel):
    score: int
    tier: Tier
    breakdown: list[ScoreItem] = Field(default_factory=list)
    complete: bool = True
    missing_fields: list[str] = Field(default_factory=list)
    disqualified_reason: str | None = None
    disqualified_by: str | None = None  # rule name, or "out_of_area"
    close_message: str | None = None


class Slot(APIModel):
    slot_id: str
    rep_id: str
    start: datetime
    end: datetime
    label: str


class Booking(APIModel):
    id: str
    lead_id: str
    rep_id: str
    rep_name: str
    office_id: str
    office_name: str
    start: datetime
    end: datetime
    label: str
    kind: str


class CRMContact(APIModel):
    id: str
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    pipeline: str | None = None
    stage: str | None = None


class Notification(APIModel):
    kind: Literal["new_lead", "hot_lead", "booked", "escalation"]
    channel: str
    title: str
    fields: dict[str, str] = Field(default_factory=dict)
    note: str | None = None
    mention: str | None = None  # slack user id or rep name
    priority: Literal["normal", "urgent"] = "normal"
    lead_id: str
    rep_id: str | None = None
    created_at: datetime

    def to_slack_payload(self) -> dict[str, Any]:
        mention = ""
        if self.mention:
            is_id = re.fullmatch(r"[UW][A-Z0-9]{6,}", self.mention)
            mention = f"<@{self.mention}> " if is_id else f"@{self.mention} "
        flag = ":rotating_light: " if self.priority == "urgent" else ""
        text = f"{flag}{mention}{self.title}"
        lines = [f"*{k}:* {v}" for k, v in self.fields.items()]
        if self.note:
            lines.append(f"_{self.note}_")
        blocks: list[dict[str, Any]] = [
            {"type": "section", "text": {"type": "mrkdwn", "text": f"*{text}*"}}
        ]
        if lines:
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "\n".join(lines)}})
        return {"text": text, "blocks": blocks}
