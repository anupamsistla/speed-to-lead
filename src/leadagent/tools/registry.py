"""Tool definitions (Anthropic tool-calling format) and a dispatcher that times every call."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from typing import Any

from leadagent.models import ToolCall
from leadagent.tools import impl
from leadagent.tools.context import ToolContext

Impl = Callable[..., dict[str, Any]]


def _schemas(ctx: ToolContext) -> dict[str, tuple[str, dict[str, Any]]]:
    q = ctx.bundle.qualification
    field_help = "; ".join(
        f"{f.key} ({f.type}{': ' + '/'.join(f.options) if f.options else ''})"
        for f in q.required_fields
    )
    obj = "object"
    return {
        "search_knowledge": (
            "Search the company knowledge base. Every hit carries its source file. Use before "
            "answering any factual question about services, financing, warranty or process. "
            "Only state facts that appear in the hits.",
            {
                "type": obj,
                "properties": {
                    "query": {"type": "string"},
                    "k": {"type": "integer", "minimum": 1, "maximum": 5, "default": 3},
                },
                "required": ["query"],
            },
        ),
        "check_existing_contact": (
            "Look up this lead in the CRM by phone and email. Call this first. If found, "
            "known answers are loaded so you do not ask for them again.",
            {"type": obj, "properties": {}},
        ),
        "score_lead": (
            "Record qualification answers the lead gave and score the lead. Also routes by zip "
            "to an office and assigns a rep. Call each time you learn new answers. Fields: "
            f"{field_help}. Contact fields name, phone and email are also accepted.",
            {
                "type": obj,
                "properties": {
                    "fields": {
                        "type": obj,
                        "description": "Answers as key/value pairs, using the field keys.",
                    }
                },
                "required": ["fields"],
            },
        ),
        "get_slots": (
            "Get appointment times for the lead's assigned office. Only works once the lead "
            "is fully qualified and not disqualified. Optionally pass a date to see that day.",
            {
                "type": obj,
                "properties": {
                    "date": {"type": "string", "description": "YYYY-MM-DD, optional"},
                },
            },
        ),
        "book_appointment": (
            "Book one of the slots returned by get_slots, using its slot_id exactly.",
            {
                "type": obj,
                "properties": {"slot_id": {"type": "string"}},
                "required": ["slot_id"],
            },
        ),
        "send_message": (
            "Send a text message to the lead. Keep it short. This is the only way the lead "
            "sees anything. Blocked automatically after opt-out and during quiet hours.",
            {
                "type": obj,
                "properties": {"body": {"type": "string"}},
                "required": ["body"],
            },
        ),
        "update_crm": (
            "Write the lead to the CRM: a short conversation summary plus all collected "
            "fields, mapped automatically. Use stage_event 'created' after qualifying (also "
            "for disqualified leads, to log them) and 'booked' after an appointment is booked.",
            {
                "type": obj,
                "properties": {
                    "summary": {"type": "string", "description": "2-4 factual sentences"},
                    "stage_event": {"type": "string", "enum": ["created", "booked"]},
                    "outcome": {
                        "type": "string",
                        "enum": ["lead", "spam"],
                        "description": "Use 'spam' for obvious spam or bots. Nothing is written "
                        "to the CRM and the lead is closed silently.",
                    },
                },
                "required": ["summary"],
            },
        ),
        "notify_rep": (
            "Notify the assigned rep in the team channel. Pass flags when the lead asked "
            "something that needs a rep to confirm (pricing, financing, guarantees).",
            {
                "type": obj,
                "properties": {
                    "note": {"type": "string"},
                    "flags": {
                        "type": "array",
                        "items": {"type": "string", "enum": list(impl.FLAG_REASONS)},
                    },
                },
            },
        ),
        "escalate_to_human": (
            "Hand the conversation to a person. Use when the lead is angry, asks for a "
            "person, or asks a second question the knowledge base cannot answer.",
            {
                "type": obj,
                "properties": {
                    "reason": {"type": "string", "enum": list(impl.ESCALATION_REASONS)},
                    "details": {"type": "string"},
                },
                "required": ["reason"],
            },
        ),
    }


_IMPLS: dict[str, Impl] = {
    "search_knowledge": impl.search_knowledge,
    "check_existing_contact": impl.check_existing_contact,
    "score_lead": impl.score_lead,
    "get_slots": impl.get_slots,
    "book_appointment": impl.book_appointment,
    "send_message": impl.send_message,
    "update_crm": impl.update_crm,
    "notify_rep": impl.notify_rep,
    "escalate_to_human": impl.escalate_to_human,
}

TOOL_NAMES = tuple(_IMPLS)


class ToolRegistry:
    def __init__(self, ctx: ToolContext):
        self.ctx = ctx
        self._schemas = _schemas(ctx)

    def definitions(self) -> list[dict[str, Any]]:
        return [
            {"name": name, "description": desc, "input_schema": schema}
            for name, (desc, schema) in self._schemas.items()
        ]

    def call(self, name: str, args: dict[str, Any] | None) -> dict[str, Any]:
        args = args or {}
        started = self.ctx.clock.now()
        t0 = time.perf_counter()
        result = self._dispatch(name, args)
        latency_ms = round((time.perf_counter() - t0) * 1000, 2)
        if self.ctx.record:
            self.ctx.record(
                ToolCall(
                    id=uuid.uuid4().hex[:12],
                    lead_id=self.ctx.session.lead.id,
                    name=name,
                    args=args,
                    result=result,
                    latency_ms=latency_ms,
                    started_at=started,
                    error="error" in result,
                )
            )
        return result

    def _dispatch(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        fn = _IMPLS.get(name)
        if fn is None:
            return impl.err(f"unknown tool '{name}'", available=list(_IMPLS))
        schema = self._schemas[name][1]
        allowed = set(schema.get("properties", {}))
        unknown = sorted(set(args) - allowed)
        if unknown:
            return impl.err(f"unexpected arguments {unknown}. Allowed: {sorted(allowed)}")
        missing = [k for k in schema.get("required", []) if k not in args]
        if missing:
            return impl.err(f"missing required arguments {missing}")
        try:
            return fn(self.ctx, **args)
        except Exception as e:  # tools must never crash the agent loop
            return impl.err(f"{type(e).__name__}: {e}")
