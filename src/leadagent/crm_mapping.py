"""Translate between engine field keys and CRM property names using crm_mapping.yaml."""

from __future__ import annotations

from typing import Any

from leadagent.config.schemas import CRMMapping
from leadagent.session import LeadSession


def internal_values(session: LeadSession, summary: str | None = None) -> dict[str, Any]:
    """Everything the engine knows about the lead, keyed by internal field name."""
    out: dict[str, Any] = dict(session.fields)
    if session.score:
        out["lead_score"] = session.score.score
        out["score_tier"] = session.score.tier
    if session.office_id:
        out["assigned_office"] = session.office_id
    if session.rep_id:
        out["assigned_rep"] = session.rep_id
    if session.booking:
        out["appointment_time"] = session.booking.start.isoformat()
    out["consent_status"] = session.consent
    out["source"] = session.lead.source
    if summary is not None:
        out["summary"] = summary
    return out


def to_crm_properties(mapping: CRMMapping, values: dict[str, Any]) -> dict[str, Any]:
    return {mapping.field_map[k]: v for k, v in values.items() if k in mapping.field_map}


def from_crm_properties(mapping: CRMMapping, props: dict[str, Any]) -> dict[str, Any]:
    inverse = {v: k for k, v in mapping.field_map.items()}
    return {inverse[k]: v for k, v in props.items() if k in inverse and v not in (None, "")}
