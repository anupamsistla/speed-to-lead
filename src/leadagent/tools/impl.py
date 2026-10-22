"""The nine agent tools. Each takes (ctx, **args) and returns a JSON-serializable dict.

Tools never raise for expected problems. They return {"error": ...} so the model can recover.
Anything the model could abuse (CRM writes, who gets notified) is built from session state,
not from free-form arguments.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from leadagent import scoring
from leadagent.crm_mapping import from_crm_properties, internal_values, to_crm_properties
from leadagent.guardrails import find_unsupported_claims, in_quiet_hours, quiet_hours_end
from leadagent.models import Notification, Slot
from leadagent.session import DeferredMessage
from leadagent.tools.context import ToolContext

MAX_MESSAGE_CHARS = 1000
CONTACT_KEYS = ("name", "phone", "email")
FLAG_REASONS = (
    "pricing_question",
    "financing_question",
    "guarantee_question",
    "needs_rep_confirmation",
    "other",
)
ESCALATION_REASONS = ("angry", "requested_human", "unanswered_twice", "other")


def err(message: str, **extra: Any) -> dict[str, Any]:
    return {"error": message, **extra}


def _spec(ctx: ToolContext, key: str):
    return next((f for f in ctx.bundle.qualification.required_fields if f.key == key), None)


# ------------------------------------------------------------------ 1 search_knowledge
def search_knowledge(ctx: ToolContext, query: str, k: int = 3) -> dict[str, Any]:
    s = ctx.session
    hits = ctx.retriever.search(query, max(1, min(int(k), 5)))
    if not hits:
        s.kb_misses += 1
        s.add_flag(f"unanswered_question: {query.strip()[:80]}")
        return {
            "found": False,
            "hits": [],
            "kb_misses": s.kb_misses,
            "escalate_recommended": s.kb_misses >= 2,
            "instruction": (
                "Nothing in the knowledge base covers this. Do not guess. Tell the lead a rep "
                "will confirm. If this is the second unanswered question, call escalate_to_human."
            ),
        }
    return {
        "found": True,
        "hits": [
            {"source": h.source, "heading": h.heading, "text": h.text, "score": round(h.score, 2)}
            for h in hits
        ],
    }


# ------------------------------------------------------- 2 check_existing_contact
def check_existing_contact(ctx: ToolContext) -> dict[str, Any]:
    s = ctx.session
    contact = ctx.adapters.crm.find_contact(phone=s.lead.phone, email=s.lead.email)
    if contact is None:
        return {"exists": False}
    s.crm_contact_id = contact.id
    if not s.lead.name and contact.name:
        s.lead.name = contact.name
    known = from_crm_properties(ctx.bundle.crm_mapping, contact.properties)
    adopted: dict[str, Any] = {}
    for key, raw in known.items():
        spec = _spec(ctx, key)
        if spec is None or key in s.fields:
            continue
        try:
            adopted[key] = scoring.normalize_value(spec, raw)
        except scoring.FieldError:
            continue
    s.fields.update(adopted)
    return {
        "exists": True,
        "contact_id": contact.id,
        "name": contact.name,
        "stage": contact.stage,
        "known_fields": adopted,
        "instruction": "Do not re-ask for known_fields. Confirm them briefly if relevant.",
    }


# ------------------------------------------------------------------- 3 score_lead
def score_lead(ctx: ToolContext, fields: dict[str, Any]) -> dict[str, Any]:
    s = ctx.session
    invalid: dict[str, str] = {}
    unknown: list[str] = []
    accepted: dict[str, Any] = {}
    for key, raw in fields.items():
        if key in CONTACT_KEYS:
            value = str(raw).strip()
            if value:
                setattr(s.lead, key, value)
                accepted[key] = value
            continue
        spec = _spec(ctx, key)
        if spec is None:
            unknown.append(key)
            continue
        try:
            s.fields[key] = accepted[key] = scoring.normalize_value(spec, raw)
        except scoring.FieldError as e:
            invalid[key] = str(e)

    result = scoring.evaluate(ctx.bundle, s.values())
    s.score = result

    office = None
    zip_code = s.fields.get("zip")
    if zip_code and result.tier != "disqualified":
        office = ctx.router.office_for_zip(zip_code)
        if office and s.office_id != office.id:
            s.office_id = office.id
            s.rep_id = ctx.router.assign_rep(office.id).id
    if result.tier == "disqualified":
        s.closed_reason = result.disqualified_by

    questions = [
        {"key": f.key, "question": f.question, "options": f.options}
        for f in ctx.bundle.qualification.required_fields
        if f.key in result.missing_fields
    ]
    out: dict[str, Any] = {
        "accepted": accepted,
        "score": result.model_dump(mode="json"),
        "still_missing": questions,
        "office": {"id": office.id, "name": office.name} if office else None,
    }
    if invalid:
        out["invalid_fields"] = invalid
    if unknown:
        out["unknown_fields"] = unknown
    if result.tier == "disqualified":
        out["instruction"] = (
            "Lead is disqualified. Send a polite close (do not book) and log it with update_crm."
        )
    elif not result.complete:
        out["instruction"] = "Score is provisional. Ask only the still_missing questions."
    return out


# ------------------------------------------------------------------- 4 get_slots
def _may_schedule(ctx: ToolContext) -> str | None:
    s = ctx.session
    if s.consent == "opted_out":
        return "lead has opted out"
    if s.human_takeover:
        return "a human has taken over"
    if s.score is None:
        return "score the lead first with score_lead"
    if s.score.tier == "disqualified":
        return "lead is disqualified and cannot be booked"
    if not s.score.complete:
        return f"still missing required fields: {s.score.missing_fields}"
    if not s.office_id:
        return "lead has not been routed to an office"
    return None


def get_slots(ctx: ToolContext, date: str | None = None) -> dict[str, Any]:
    blocked = _may_schedule(ctx)
    if blocked:
        return err(blocked)
    s = ctx.session
    cfg = ctx.bundle.routing.appointment
    tz = ZoneInfo(ctx.bundle.company.timezone)
    now = ctx.clock.now()
    earliest = now + timedelta(hours=cfg.minimum_notice_hours)
    latest = now + timedelta(days=cfg.lookahead_days)
    if date:
        try:
            day = datetime.strptime(date, "%Y-%m-%d").date()
        except ValueError:
            return err("date must be YYYY-MM-DD")
        earliest = max(earliest, datetime.combine(day, time.min, tzinfo=tz))
        latest = min(latest, datetime.combine(day + timedelta(days=1), time.min, tzinfo=tz))
        if earliest >= latest:
            return err(f"{date} is outside the bookable window")

    reps = [r.id for r in ctx.router.rep_order(s.office_id, first=s.rep_id)]
    free = ctx.adapters.calendar.get_slots(
        reps, start=earliest, end=latest, duration_minutes=cfg.duration_minutes
    )
    chosen = _pick(
        free,
        cfg.slots_to_offer,
        spread=not (s.score.tier == "hot" and ctx.bundle.routing.hot_lead.offer_earliest_slot),
    )
    for slot in chosen:
        s.offered_slots[slot.slot_id] = slot
    if not chosen:
        s.add_flag("no_availability")
        return {
            "slots": [],
            "note": "No openings in the window. Tell the lead a rep will follow up.",
        }
    return {
        "slots": [{"slot_id": c.slot_id, "label": c.label} for c in chosen],
        "timezone": ctx.bundle.company.timezone,
        "duration_minutes": cfg.duration_minutes,
    }


def _pick(slots: list[Slot], n: int, *, spread: bool) -> list[Slot]:
    """Earliest n, or (spread) at most one per day first so the lead sees real choice."""
    if not spread:
        return slots[:n]
    picked: list[Slot] = []
    days: set = set()
    for slot in slots:
        if slot.start.date() not in days:
            picked.append(slot)
            days.add(slot.start.date())
        if len(picked) == n:
            break
    for slot in slots:
        if len(picked) >= n:
            break
        if slot not in picked:
            picked.append(slot)
    return sorted(picked, key=lambda x: x.start)


# ------------------------------------------------------------- 5 book_appointment
def book_appointment(ctx: ToolContext, slot_id: str) -> dict[str, Any]:
    s = ctx.session
    if s.booking:
        return err("already booked", booking=s.booking.model_dump(mode="json"))
    blocked = _may_schedule(ctx)
    if blocked:
        return err(blocked)
    slot = s.offered_slots.get(slot_id)
    if slot is None:
        return err("unknown slot_id. Offer slots with get_slots and use one of its slot_id values.")
    rep, office = ctx.router.rep(slot.rep_id)
    try:
        booking = ctx.adapters.calendar.book(
            slot=slot,
            lead=s.lead,
            office_id=office.id,
            office_name=office.name,
            rep_name=rep.name,
            kind=ctx.bundle.routing.appointment.kind,
        )
    except ValueError as e:
        s.offered_slots.pop(slot_id, None)
        return err(str(e) + ". Call get_slots again.")
    s.booking = booking
    s.rep_id = rep.id
    s.office_id = office.id
    return {"booked": True, "booking": booking.model_dump(mode="json")}


# ------------------------------------------------------------------ 6 send_message
def send_message(ctx: ToolContext, body: str) -> dict[str, Any]:
    s = ctx.session
    body = (body or "").strip()
    if not body:
        return err("message body is empty")
    if len(body) > MAX_MESSAGE_CHARS:
        return err(f"message is {len(body)} chars. Keep it under {MAX_MESSAGE_CHARS}.")
    if s.consent == "opted_out":
        return {"sent": False, "blocked": "opted_out"}
    if s.human_takeover:
        return {"sent": False, "blocked": "human_takeover"}

    knowledge = "\n".join(d.text for d in ctx.bundle.knowledge)
    problems = find_unsupported_claims(body, knowledge, s.inbound_text())
    if problems:
        s.add_flag("unsupported_claim_blocked")
        s.log_event("claim_blocked", ctx.clock.now(), problems=problems)
        return {
            "sent": False,
            "blocked": "unsupported_claim",
            "problems": problems,
            "instruction": (
                "Rewrite without these claims. Say a rep will confirm that detail, and call "
                "notify_rep with the matching flag so the rep follows up."
            ),
        }

    now = ctx.clock.now()
    if in_quiet_hours(ctx.bundle.company, now):
        deliver_after = quiet_hours_end(ctx.bundle.company, now)
        s.deferred.append(DeferredMessage(body=body, deliver_after=deliver_after))
        return {"sent": False, "blocked": "quiet_hours", "deliver_after": deliver_after.isoformat()}

    msg = ctx.adapters.channel.send(s.lead, body)
    s.messages.append(msg)
    if s.first_response_seconds is None:
        s.first_response_seconds = round((now - s.lead.created_at).total_seconds(), 2)
    return {
        "sent": True,
        "message_id": msg.id,
        "first_response_seconds": s.first_response_seconds,
    }


# ------------------------------------------------------------------ 7 update_crm
def update_crm(
    ctx: ToolContext, summary: str, stage_event: str = "created", outcome: str = "lead"
) -> dict[str, Any]:
    s = ctx.session
    mapping = ctx.bundle.crm_mapping
    if stage_event not in ("created", "booked"):
        return err("stage_event must be 'created' or 'booked'")
    if outcome not in ("lead", "spam"):
        return err("outcome must be 'lead' or 'spam'")
    if outcome == "spam":
        # Spam is logged in our own records, never pushed into the company's CRM pipeline.
        s.closed_reason = "spam"
        s.add_flag("spam")
        return {"logged": True, "crm_written": False, "outcome": "spam"}
    if stage_event == "booked" and not s.booking:
        return err("cannot move to the booked stage before an appointment is booked")
    summary = (summary or "").strip()
    if not summary:
        return err("summary is required")

    stage = mapping.stage_on_booked if stage_event == "booked" else mapping.stage_on_create
    properties = to_crm_properties(mapping, internal_values(s, summary))
    contact = ctx.adapters.crm.upsert_contact(
        name=s.lead.name,
        phone=s.lead.phone,
        email=s.lead.email,
        properties=properties,
        pipeline=mapping.pipeline,
        stage=stage,
    )
    s.crm_contact_id = contact.id
    s.crm_stage = stage_event
    s.crm_summary = summary
    return {
        "contact_id": contact.id,
        "pipeline": mapping.pipeline,
        "stage": stage,
        "properties_written": properties,
    }


# ----------------------------------------------------------------- 8 notify_rep
def notify_rep(
    ctx: ToolContext, note: str | None = None, flags: list[str] | None = None
) -> dict[str, Any]:
    s = ctx.session
    if not s.rep_id:
        return err("no rep assigned (lead is disqualified or not yet routed)")
    bad = [f for f in (flags or []) if f not in FLAG_REASONS]
    if bad:
        return err(f"unknown flags {bad}. Allowed: {list(FLAG_REASONS)}")
    for f in flags or []:
        s.add_flag(f)

    rep, office = ctx.router.rep(s.rep_id)
    cfg = ctx.bundle.routing.hot_lead
    hot = bool(s.score and s.score.tier == "hot")
    urgent = hot and cfg.notify == "immediate"
    kind = "booked" if s.booking else ("hot_lead" if hot else "new_lead")
    who = s.lead.name or s.lead.phone or s.lead.email or "New lead"
    tier = s.score.tier if s.score else "unscored"
    fields: dict[str, str] = {
        "Score": f"{s.score.score}/100 ({tier})" if s.score else "unscored",
        "Office": office.name,
        "Rep": rep.name,
    }
    if s.booking:
        fields["Appointment"] = f"{s.booking.label} ({s.booking.kind})"
    if s.lead.phone:
        fields["Phone"] = s.lead.phone
    if s.lead.email:
        fields["Email"] = s.lead.email
    for f in ctx.bundle.qualification.required_fields:
        if f.key in s.fields:
            fields[f.key.replace("_", " ").title()] = str(s.fields[f.key])
    if s.flags:
        fields["Flags"] = "; ".join(s.flags)
    if s.crm_contact_id:
        fields["CRM"] = s.crm_contact_id

    mention = rep.slack_user_id
    if urgent and cfg.slack_mention:
        mention = rep.slack_user_id or rep.name
    notification = Notification(
        kind=kind,
        channel=ctx.bundle.routing.slack_channel,
        title=f"{'Hot lead' if hot else 'New lead'}: {who}"
        + (f" booked for {s.booking.label}" if s.booking else ""),
        fields=fields,
        note=(note or "").strip()[:300] or None,
        mention=mention,
        priority="urgent" if urgent else "normal",
        lead_id=s.lead.id,
        rep_id=rep.id,
        created_at=ctx.clock.now(),
    )
    ctx.adapters.notifier.notify(notification)
    s.notified_kinds.append(kind)
    return {
        "notified": True,
        "kind": kind,
        "priority": notification.priority,
        "channel": notification.channel,
        "rep": rep.name,
    }


# ------------------------------------------------------------ 9 escalate_to_human
def escalate_to_human(ctx: ToolContext, reason: str, details: str | None = None) -> dict[str, Any]:
    s = ctx.session
    if reason not in ESCALATION_REASONS:
        return err(f"reason must be one of {list(ESCALATION_REASONS)}")
    if s.escalated:
        return {"escalated": True, "already": True}
    s.escalated = True
    s.escalation_reason = reason
    s.add_flag(f"escalated: {reason}")

    rep_name = None
    mention = None
    if s.rep_id:
        rep, _ = ctx.router.rep(s.rep_id)
        rep_name, mention = rep.name, rep.slack_user_id or rep.name
    who = s.lead.name or s.lead.phone or s.lead.email or "Lead"
    ctx.adapters.notifier.notify(
        Notification(
            kind="escalation",
            channel=ctx.bundle.routing.slack_channel,
            title=f"Needs a human: {who} ({reason.replace('_', ' ')})",
            fields={
                k: v
                for k, v in {
                    "Phone": s.lead.phone,
                    "Email": s.lead.email,
                    "Rep": rep_name,
                }.items()
                if v
            },
            note=(details or "").strip()[:300] or None,
            mention=mention,
            priority="urgent",
            lead_id=s.lead.id,
            rep_id=s.rep_id,
            created_at=ctx.clock.now(),
        )
    )
    return {
        "escalated": True,
        "reason": reason,
        "instruction": "Send one short handoff message to the lead, then stop messaging.",
    }
