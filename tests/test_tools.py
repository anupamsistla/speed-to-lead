"""Unit tests for the nine tools, called through the registry like the agent will."""

from __future__ import annotations

from datetime import timedelta

from leadagent.tools import TOOL_NAMES
from tests.conftest import HOT_FIELDS, NIGHT_TIME


def qualify(reg, **over):
    return reg.call("score_lead", {"fields": {**HOT_FIELDS, **over}})


# ------------------------------------------------------------------ registry
def test_registry_exposes_exactly_the_nine_tools(make_ctx):
    _, reg = make_ctx()
    assert set(TOOL_NAMES) == {
        "search_knowledge",
        "check_existing_contact",
        "score_lead",
        "get_slots",
        "book_appointment",
        "send_message",
        "update_crm",
        "notify_rep",
        "escalate_to_human",
    }
    defs = reg.definitions()
    assert [d["name"] for d in defs] == list(TOOL_NAMES)
    assert all(d["input_schema"]["type"] == "object" and d["description"] for d in defs)
    # field keys come from config, so the model is told what to collect
    score_desc = next(d for d in defs if d["name"] == "score_lead")["description"]
    assert "monthly_bill" in score_desc and "asphalt_shingle" in score_desc


def test_registry_validates_and_records(make_ctx):
    ctx, reg = make_ctx()
    assert "unknown tool" in reg.call("nope", {})["error"]
    assert "unexpected arguments" in reg.call("send_message", {"body": "x", "evil": 1})["error"]
    assert "missing required" in reg.call("send_message", {})["error"]
    reg.call("check_existing_contact", {})
    last = ctx.calls[-1]
    assert last.name == "check_existing_contact" and last.latency_ms >= 0 and not last.error
    assert ctx.calls[0].error  # errors are recorded too


# ------------------------------------------------------------ search_knowledge
def test_search_knowledge_returns_sources(make_ctx):
    ctx, reg = make_ctx()
    r = reg.call("search_knowledge", {"query": "how long is the workmanship warranty"})
    assert r["found"] and r["hits"][0]["source"] == "knowledge/warranty.md"
    assert ctx.session.kb_misses == 0


def test_search_knowledge_miss_counts_and_recommends_escalation_on_second(make_ctx):
    ctx, reg = make_ctx()
    first = reg.call("search_knowledge", {"query": "do you install pool heaters"})
    assert not first["found"] and first["kb_misses"] == 1 and not first["escalate_recommended"]
    second = reg.call("search_knowledge", {"query": "can you paint my fence"})
    assert second["kb_misses"] == 2 and second["escalate_recommended"]
    assert any(f.startswith("unanswered_question") for f in ctx.session.flags)


# ------------------------------------------------------- check_existing_contact
def test_existing_contact_prefills_known_fields(make_ctx):
    ctx, reg = make_ctx()
    ctx.adapters.crm.seed_contact(
        name="Jamie Rivera",
        phone="303-555-0142",
        properties={"homeowner_status": "owner", "roof_type": "tile", "bogus": "x"},
    )
    r = reg.call("check_existing_contact", {})
    assert r["exists"] and r["known_fields"] == {"homeowner": "owner", "roof_type": "tile"}
    assert ctx.session.fields["roof_type"] == "tile" and ctx.session.crm_contact_id
    # a second call does not overwrite answers the lead already gave
    ctx.session.fields["roof_type"] = "metal"
    reg.call("check_existing_contact", {})
    assert ctx.session.fields["roof_type"] == "metal"


def test_no_existing_contact(make_ctx):
    _, reg = make_ctx()
    assert reg.call("check_existing_contact", {}) == {"exists": False}


def test_existing_contact_fills_missing_name(make_ctx):
    ctx, reg = make_ctx(name=None)
    ctx.adapters.crm.seed_contact(name="Jamie Rivera", phone="3035550142")
    reg.call("check_existing_contact", {})
    assert ctx.session.lead.name == "Jamie Rivera"


# ------------------------------------------------------------------ score_lead
def test_score_lead_scores_routes_and_assigns(make_ctx):
    ctx, reg = make_ctx()
    r = qualify(reg)
    assert r["score"]["tier"] == "hot" and r["score"]["score"] == 90
    assert r["office"] == {"id": "denver", "name": "Denver Office"}
    assert r["still_missing"] == []
    assert ctx.session.rep_id == "maya_ortiz" and ctx.session.office_id == "denver"
    assert ctx.session.fields["roof_type"] == "asphalt_shingle"
    assert ctx.session.fields["monthly_bill"] == 250.0


def test_score_lead_partial_asks_only_whats_missing(make_ctx):
    _, reg = make_ctx()
    r = reg.call("score_lead", {"fields": {"zip": "80905", "homeowner": "owner"}})
    keys = [q["key"] for q in r["still_missing"]]
    assert keys == ["monthly_bill", "roof_type", "timeline"]
    assert r["still_missing"][1]["options"]  # choice options included
    assert r["office"]["id"] == "colorado_springs"
    assert "provisional" in r["instruction"]


def test_score_lead_reports_invalid_and_unknown_fields(make_ctx):
    ctx, reg = make_ctx()
    r = reg.call(
        "score_lead", {"fields": {"zip": "abc", "favorite_color": "red", "roof_type": "tile"}}
    )
    assert "zip" in r["invalid_fields"] and r["unknown_fields"] == ["favorite_color"]
    assert ctx.session.fields == {"roof_type": "tile"}


def test_score_lead_accepts_contact_fields(make_ctx):
    ctx, reg = make_ctx()
    reg.call("score_lead", {"fields": {"email": "jamie@example.com", "name": "Jamie R"}})
    assert ctx.session.lead.email == "jamie@example.com" and ctx.session.lead.name == "Jamie R"


def test_score_lead_out_of_area_is_disqualified_and_unassigned(make_ctx):
    ctx, reg = make_ctx()
    r = qualify(reg, zip="10001")
    assert r["score"]["tier"] == "disqualified" and r["score"]["disqualified_by"] == "out_of_area"
    assert r["office"] is None and ctx.session.rep_id is None
    assert ctx.session.closed_reason == "out_of_area"


def test_score_lead_renter_disqualified_has_close_message(make_ctx):
    ctx, reg = make_ctx()
    r = qualify(reg, homeowner="renter")
    assert r["score"]["tier"] == "disqualified" and r["score"]["close_message"]
    assert "do not book" in r["instruction"].lower()
    assert ctx.session.closed_reason == "renter"


def test_round_robin_across_leads_in_same_office(make_ctx, bundle):
    # Router state is per context here, so assign twice through the same router
    ctx, reg = make_ctx()
    qualify(reg)
    first = ctx.session.rep_id
    ctx.session.office_id = None
    qualify(reg)
    assert (first, ctx.session.rep_id) == ("maya_ortiz", "dan_whitaker")


# --------------------------------------------------------- get_slots / booking
def test_get_slots_requires_a_qualified_lead(make_ctx):
    _, reg = make_ctx()
    assert "score the lead first" in reg.call("get_slots", {})["error"]
    reg.call("score_lead", {"fields": {"zip": "80205"}})
    assert "missing required fields" in reg.call("get_slots", {})["error"]
    qualify(reg, homeowner="renter")
    assert "disqualified" in reg.call("get_slots", {})["error"]


def test_hot_lead_gets_earliest_slots_respecting_min_notice(make_ctx, clock):
    ctx, reg = make_ctx()
    qualify(reg)
    r = reg.call("get_slots", {})
    starts = [ctx.session.offered_slots[s["slot_id"]].start for s in r["slots"]]
    assert len(starts) == 3 and starts == sorted(starts)
    # now is 10:00, minimum notice 2h, so earliest is 12:00 same day
    assert starts[0] == clock.now().replace(hour=12)
    assert starts[1] - starts[0] == timedelta(minutes=30)


def test_warm_lead_gets_spread_across_days(make_ctx):
    ctx, reg = make_ctx()
    qualify(reg, monthly_bill=150, timeline="three_to_six_months")
    assert ctx.session.score.tier == "warm"
    r = reg.call("get_slots", {})
    days = {ctx.session.offered_slots[s["slot_id"]].start.date() for s in r["slots"]}
    assert len(days) == 3


def test_get_slots_for_a_specific_date(make_ctx):
    ctx, reg = make_ctx()
    qualify(reg)
    r = reg.call("get_slots", {"date": "2026-10-29"})
    assert r["slots"] and all("Oct 29" in s["label"] for s in r["slots"])
    assert "outside" in reg.call("get_slots", {"date": "2026-12-25"})["error"]
    assert "YYYY-MM-DD" in reg.call("get_slots", {"date": "tomorrow"})["error"]


def test_book_appointment_happy_path(make_ctx):
    ctx, reg = make_ctx()
    qualify(reg)
    slot_id = reg.call("get_slots", {})["slots"][0]["slot_id"]
    r = reg.call("book_appointment", {"slot_id": slot_id})
    assert r["booked"] and r["booking"]["office_id"] == "denver"
    assert ctx.session.booking and ctx.session.booking.rep_id == "maya_ortiz"
    # the slot is gone for everyone and a second booking is refused
    assert "already booked" in reg.call("book_appointment", {"slot_id": slot_id})["error"]


def test_book_rejects_invented_slot_ids(make_ctx):
    _, reg = make_ctx()
    qualify(reg)
    reg.call("get_slots", {})
    r = reg.call("book_appointment", {"slot_id": "maya_ortiz@2026-10-27T11:00:00-06:00"})
    assert "unknown slot_id" in r["error"]


def test_book_handles_slot_taken_in_between(make_ctx, bundle):
    ctx, reg = make_ctx()
    qualify(reg)
    slot_id = reg.call("get_slots", {})["slots"][0]["slot_id"]
    slot = ctx.session.offered_slots[slot_id]
    other = ctx.session.lead.model_copy(update={"id": "someone_else"})
    ctx.adapters.calendar.book(
        slot=slot,
        lead=other,
        office_id="denver",
        office_name="Denver Office",
        rep_name="Maya",
        kind="k",
    )
    r = reg.call("book_appointment", {"slot_id": slot_id})
    assert "no longer available" in r["error"] and slot_id not in ctx.session.offered_slots
    assert ctx.session.booking is None


def test_booking_blocked_after_opt_out(make_ctx):
    ctx, reg = make_ctx()
    qualify(reg)
    slot_id = reg.call("get_slots", {})["slots"][0]["slot_id"]
    ctx.session.consent = "opted_out"
    assert "opted out" in reg.call("book_appointment", {"slot_id": slot_id})["error"]
    assert "opted out" in reg.call("get_slots", {})["error"]


# ---------------------------------------------------------------- send_message
def test_send_message_sends_and_records_first_response(make_ctx, clock):
    ctx, reg = make_ctx()
    clock.advance(seconds=38)
    r = reg.call("send_message", {"body": "Hi Jamie, thanks for reaching out."})
    assert r["sent"] and r["first_response_seconds"] == 38
    assert ctx.adapters.channel.outbox[0].body.startswith("Hi Jamie")
    clock.advance(seconds=20)
    reg.call("send_message", {"body": "Second message"})
    assert ctx.session.first_response_seconds == 38  # only the first counts
    assert len(ctx.session.messages) == 2


def test_send_message_blocked_when_opted_out(make_ctx):
    ctx, reg = make_ctx()
    ctx.session.consent = "opted_out"
    assert reg.call("send_message", {"body": "hello"}) == {"sent": False, "blocked": "opted_out"}
    assert ctx.adapters.channel.outbox == []


def test_send_message_blocked_on_human_takeover(make_ctx):
    ctx, reg = make_ctx()
    ctx.session.human_takeover = True
    assert reg.call("send_message", {"body": "hello"})["blocked"] == "human_takeover"


def test_send_message_deferred_in_quiet_hours(make_ctx, clock):
    ctx, reg = make_ctx()
    clock.set(NIGHT_TIME)
    r = reg.call("send_message", {"body": "hello"})
    assert r["sent"] is False and r["blocked"] == "quiet_hours"
    assert r["deliver_after"].startswith("2026-10-28T08:00")
    assert ctx.adapters.channel.outbox == [] and ctx.session.first_response_seconds is None
    assert ctx.session.deferred[0].body == "hello"


def test_send_message_validates_body(make_ctx):
    _, reg = make_ctx()
    assert "empty" in reg.call("send_message", {"body": "   "})["error"]
    assert "chars" in reg.call("send_message", {"body": "x" * 1001})["error"]


# ------------------------------------------------------------------ update_crm
def test_update_crm_writes_mapped_fields_and_stage(make_ctx):
    ctx, reg = make_ctx()
    qualify(reg)
    r = reg.call("update_crm", {"summary": "Owner, $250 bill, wants solar ASAP."})
    assert r["stage"] == "New Lead" and r["pipeline"] == "Residential Sales"
    props = r["properties_written"]
    assert props["homeowner_status"] == "owner" and props["monthly_electric_bill"] == 250.0
    assert props["lead_score"] == 90 and props["lead_tier"] == "hot"
    assert props["assigned_office"] == "denver" and props["sms_consent"] == "unknown"
    assert props["conversation_summary"].startswith("Owner")
    stored = ctx.adapters.crm.get(r["contact_id"])
    assert stored.stage == "New Lead" and stored.phone == "+13035550142"


def test_update_crm_booked_moves_stage_on_same_contact(make_ctx):
    ctx, reg = make_ctx()
    qualify(reg)
    first = reg.call("update_crm", {"summary": "s"})
    assert (
        "before an appointment"
        in reg.call("update_crm", {"summary": "s", "stage_event": "booked"})["error"]
    )
    reg.call("book_appointment", {"slot_id": reg.call("get_slots", {})["slots"][0]["slot_id"]})
    second = reg.call("update_crm", {"summary": "s2", "stage_event": "booked"})
    assert second["contact_id"] == first["contact_id"] and second["stage"] == "Consultation Booked"
    assert "consultation_time" in second["properties_written"]


def test_update_crm_logs_disqualified_leads(make_ctx):
    _, reg = make_ctx()
    qualify(reg, zip="10001")
    r = reg.call("update_crm", {"summary": "Out of area."})
    assert r["properties_written"]["lead_tier"] == "disqualified"


def test_update_crm_validates(make_ctx):
    _, reg = make_ctx()
    assert "stage_event" in reg.call("update_crm", {"summary": "s", "stage_event": "won"})["error"]
    assert "summary" in reg.call("update_crm", {"summary": "  "})["error"]


# ------------------------------------------------------------------ notify_rep
def test_notify_rep_hot_lead_is_urgent_with_details(make_ctx):
    ctx, reg = make_ctx()
    qualify(reg)
    reg.call("update_crm", {"summary": "s"})
    r = reg.call("notify_rep", {"note": "Wants a call today"})
    assert r["priority"] == "urgent" and r["kind"] == "hot_lead" and r["rep"] == "Maya Ortiz"
    [n] = ctx.adapters.notifier.sent
    assert n.channel == "#new-leads" and n.mention == "Maya Ortiz"
    assert n.fields["Score"] == "90/100 (hot)" and n.fields["Office"] == "Denver Office"
    assert n.fields["Monthly Bill"] == "250.0" and "CRM" in n.fields
    assert n.note == "Wants a call today"


def test_notify_rep_after_booking_and_flags(make_ctx):
    ctx, reg = make_ctx()
    qualify(reg, monthly_bill=150, timeline="three_to_six_months")
    reg.call("book_appointment", {"slot_id": reg.call("get_slots", {})["slots"][0]["slot_id"]})
    r = reg.call("notify_rep", {"flags": ["financing_question"]})
    assert r["kind"] == "booked" and r["priority"] == "normal"
    [n] = ctx.adapters.notifier.sent
    assert "Appointment" in n.fields and "financing_question" in n.fields["Flags"]
    assert n.mention is None  # warm lead, rep has no slack id


def test_notify_rep_rejects_unrouted_and_bad_flags(make_ctx):
    _, reg = make_ctx()
    assert "no rep assigned" in reg.call("notify_rep", {})["error"]
    qualify(reg)
    assert "unknown flags" in reg.call("notify_rep", {"flags": ["spam"]})["error"]


def test_notify_rep_never_for_disqualified(make_ctx):
    ctx, reg = make_ctx()
    qualify(reg, homeowner="renter")
    assert "error" in reg.call("notify_rep", {})
    assert ctx.adapters.notifier.sent == []


# ------------------------------------------------------------ escalate_to_human
def test_escalate_marks_session_and_notifies_urgently(make_ctx):
    ctx, reg = make_ctx()
    qualify(reg)
    r = reg.call("escalate_to_human", {"reason": "angry", "details": "Says nobody called back"})
    assert r["escalated"] and ctx.session.escalated and ctx.session.escalation_reason == "angry"
    [n] = ctx.adapters.notifier.sent
    assert n.kind == "escalation" and n.priority == "urgent" and "angry" in n.title
    assert n.note == "Says nobody called back" and n.fields["Rep"] == "Maya Ortiz"
    assert "escalated: angry" in ctx.session.flags


def test_escalate_is_idempotent_and_works_unrouted(make_ctx):
    ctx, reg = make_ctx()
    reg.call("escalate_to_human", {"reason": "requested_human"})
    again = reg.call("escalate_to_human", {"reason": "angry"})
    assert again["already"] and len(ctx.adapters.notifier.sent) == 1
    assert ctx.session.escalation_reason == "requested_human"


def test_escalate_validates_reason(make_ctx):
    _, reg = make_ctx()
    assert "reason" in reg.call("escalate_to_human", {"reason": "bored"})["error"]
