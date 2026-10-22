"""Turn a LeadSession plus its stored records into the API's response objects."""

from __future__ import annotations

from leadagent.config.schemas import CompanyBundle
from leadagent.crm_mapping import internal_values, to_crm_properties
from leadagent.models import Notification, ToolCall
from leadagent.routing import Router
from leadagent.server.schemas import (
    CRMPreview,
    DeferredView,
    LeadDetail,
    LeadStatus,
    LeadSummary,
    RoutingView,
)
from leadagent.session import LeadSession


def status_of(s: LeadSession) -> LeadStatus:
    if s.consent == "opted_out":
        return "opted_out"
    if s.human_takeover:
        return "human"
    if s.escalated:
        return "escalated"
    if s.booking:
        return "booked"
    if s.closed_reason == "spam":
        return "spam"
    if s.closed_reason:
        return "closed"
    if not s.messages and not s.history:
        return "new"
    return "in_progress"


def summarize(company: str, s: LeadSession) -> LeadSummary:
    return LeadSummary(
        id=s.lead.id,
        company=company,
        name=s.lead.name,
        phone=s.lead.phone,
        source=s.lead.source,
        created_at=s.lead.created_at,
        status=status_of(s),
        score=s.score.score if s.score else None,
        tier=s.score.tier if s.score else None,
        first_response_seconds=s.first_response_seconds,
        consent=s.consent,
        booked=s.booking is not None,
        escalated=s.escalated,
    )


def routing_view(bundle: CompanyBundle, router: Router, s: LeadSession) -> RoutingView:
    if not s.office_id:
        reason = None
        if s.score and s.score.disqualified_by == "out_of_area":
            reason = s.score.disqualified_reason
        return RoutingView(
            office_id=None, office_name=None, rep_id=None, rep_name=None, reason=reason
        )
    office = router.office(s.office_id)
    rep_name = None
    if s.rep_id:
        rep_name = router.rep(s.rep_id)[0].name
    zip_code = s.fields.get("zip")
    return RoutingView(
        office_id=office.id,
        office_name=office.name,
        rep_id=s.rep_id,
        rep_name=rep_name,
        reason=f"Zip {zip_code} is served by {office.name}. Rep assigned by round robin.",
    )


def crm_preview(bundle: CompanyBundle, s: LeadSession) -> CRMPreview:
    mapping = bundle.crm_mapping
    stage = None
    if s.crm_stage == "booked":
        stage = mapping.stage_on_booked
    elif s.crm_stage == "created":
        stage = mapping.stage_on_create
    return CRMPreview(
        contact_id=s.crm_contact_id,
        pipeline=mapping.pipeline,
        stage=stage,
        synced=s.crm_stage is not None,
        properties=to_crm_properties(mapping, internal_values(s, s.crm_summary)),
    )


def detail(
    company: str,
    bundle: CompanyBundle,
    router: Router,
    s: LeadSession,
    notifications: list[Notification],
    tool_calls: list[ToolCall],
) -> LeadDetail:
    missing = (
        s.score.missing_fields
        if s.score
        else [f.key for f in bundle.qualification.required_fields if f.key not in s.fields]
    )
    return LeadDetail(
        summary=summarize(company, s),
        lead=s.lead,
        messages=s.messages,
        answers=s.fields,
        missing_fields=missing,
        score=s.score,
        routing=routing_view(bundle, router, s),
        booking=s.booking,
        crm=crm_preview(bundle, s),
        notifications=notifications,
        tool_calls=tool_calls,
        flags=s.flags,
        events=s.events,
        deferred=[DeferredView(body=d.body, deliver_after=d.deliver_after) for d in s.deferred],
    )
