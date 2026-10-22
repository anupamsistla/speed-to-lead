"""Company #2 runs on the same engine with config changes only (definition of done 1)."""

from __future__ import annotations

import pytest

from leadagent.adapters import build_adapters
from leadagent.agent import build_system_prompt
from leadagent.clock import FixedClock
from leadagent.config import list_companies, load_company
from leadagent.llm import reply, text, tool_use
from leadagent.models import Lead
from leadagent.retrieval import BM25Retriever
from leadagent.routing import Router
from leadagent.session import LeadSession
from leadagent.tools import ToolContext, ToolRegistry
from tests.conftest import BUSINESS_TIME, FORM

SLUG = "first_lakes_mortgage"
HOT = {
    "zip": "55408",
    "loan_purpose": "purchase",
    "credit_range": "740+",
    "loan_type": "conventional",
    "estimated_price": "$450,000",
    "timeline": "within 30 days",
}


@pytest.fixture(scope="module")
def mortgage():
    return load_company(SLUG)


def ctx_for(bundle, **lead_kw):
    clock = FixedClock(BUSINESS_TIME)
    retriever = BM25Retriever()
    retriever.index(bundle.knowledge)
    lead = Lead(
        id="m1", name="Greta Halvorsen", phone="+16125550101", created_at=clock.now(), **lead_kw
    )
    ctx = ToolContext(
        bundle=bundle,
        session=LeadSession(lead=lead),
        adapters=build_adapters(bundle, clock, env={}),
        retriever=retriever,
        router=Router(bundle.routing),
        clock=clock,
    )
    return ctx, ToolRegistry(ctx)


def test_both_companies_are_discovered_and_differ_in_every_config_file(mortgage):
    assert {"sunrise_solar", SLUG} <= set(list_companies())
    solar = load_company("sunrise_solar")
    assert (
        mortgage.company.name != solar.company.name
        and mortgage.company.brand_color != solar.company.brand_color
    )
    assert mortgage.qualification.field_keys == [
        "zip",
        "loan_purpose",
        "credit_range",
        "loan_type",
        "estimated_price",
        "timeline",
    ]
    assert set(mortgage.qualification.field_keys) != set(solar.qualification.field_keys)
    assert [o.id for o in mortgage.routing.offices] == ["minneapolis", "milwaukee", "madison"]
    assert sum(len(o.reps) for o in mortgage.routing.offices) == 9
    assert mortgage.routing.appointment.kind == "mortgage consultation call"
    assert (
        mortgage.routing.appointment.duration_minutes
        == 30
        != solar.routing.appointment.duration_minutes
    )
    assert mortgage.crm_mapping.pipeline == "Mortgage Pipeline"
    assert mortgage.crm_mapping.field_map["credit_range"] == "credit_band"
    assert mortgage.routing.slack_channel == "#mortgage-leads"
    assert mortgage.company.timezone == "America/Chicago"


@pytest.mark.parametrize("slug", ["sunrise_solar", SLUG])
def test_the_prompt_is_built_from_each_companys_config(slug):
    b = load_company(slug)
    p = build_system_prompt(b)
    assert b.company.name in p and b.routing.appointment.kind in p
    for f in b.qualification.required_fields:
        assert f.key in p and f.question in p
    other = load_company(SLUG if slug == "sunrise_solar" else "sunrise_solar")
    assert other.company.name not in p and other.routing.appointment.kind not in p


def test_a_hot_borrower_is_scored_routed_and_booked_with_the_mortgage_config(mortgage):
    ctx, reg = ctx_for(mortgage, email="greta@example.com")
    r = reg.call("score_lead", {"fields": HOT})
    assert r["score"]["tier"] == "hot" and r["score"]["score"] == 100
    assert {i["rule"] for i in r["score"]["breakdown"]} == {
        "credit_740_plus",
        "closing_within_30_days",
        "purchase_loan",
        "knows_loan_type",
        "price_200k_plus",
        "has_email",
    }
    assert r["office"] == {"id": "minneapolis", "name": "Minneapolis Office"}
    assert (
        ctx.session.fields["credit_range"] == "740_plus"
        and ctx.session.fields["estimated_price"] == 450000.0
    )

    slots = reg.call("get_slots", {})
    assert len(slots["slots"]) == 3 and slots["duration_minutes"] == 30
    offered = [ctx.session.offered_slots[s["slot_id"]] for s in slots["slots"]]
    assert all((s.end - s.start).total_seconds() == 1800 for s in offered)
    # the config sets 1 hour of minimum notice, business hours are 8am to 6pm Central
    assert offered[0].start.hour == 12  # clock is 11:00 Central, plus 1 hour of notice

    booked = reg.call("book_appointment", {"slot_id": slots["slots"][0]["slot_id"]})["booking"]
    assert (
        booked["kind"] == "mortgage consultation call"
        and booked["office_name"] == "Minneapolis Office"
    )

    crm = reg.call("update_crm", {"summary": "Hot purchase lead.", "stage_event": "booked"})
    assert crm["pipeline"] == "Mortgage Pipeline" and crm["stage"] == "Consultation Scheduled"
    props = crm["properties_written"]
    assert props["credit_band"] == "740_plus" and props["branch"] == "minneapolis"
    assert props["loan_program"] == "conventional" and props["estimated_property_value"] == 450000.0
    assert "inquiry_notes" in props and "consultation_scheduled_for" in props
    assert not {"homeowner_status", "roof_type", "monthly_electric_bill"} & set(props)

    reg.call("notify_rep", {})
    [n] = ctx.adapters.notifier.sent
    assert n.channel == "#mortgage-leads" and n.fields["Office"] == "Minneapolis Office"
    assert n.fields["Credit Range"] == "740_plus" and "Mortgage consultation call" not in n.title


@pytest.mark.parametrize(
    ("override", "by"),
    [
        ({"credit_range": "under 580"}, "credit_below_minimum"),
        ({"estimated_price": 60000}, "loan_too_small"),
        ({"zip": "75201"}, "out_of_area"),
    ],
)
def test_borrowers_who_cannot_be_served_are_closed_not_booked(mortgage, override, by):
    ctx, reg = ctx_for(mortgage)
    r = reg.call("score_lead", {"fields": {**HOT, **override}})
    assert r["score"]["tier"] == "disqualified" and r["score"]["disqualified_by"] == by
    assert "disqualified" in reg.call("get_slots", {})["error"]
    assert ctx.session.rep_id is None


def test_routing_follows_zip_and_each_office_has_its_own_reps(mortgage):
    for zip_code, office in (
        ("53207", "milwaukee"),
        ("53703", "madison"),
        ("55414", "minneapolis"),
    ):
        ctx, reg = ctx_for(mortgage)
        r = reg.call("score_lead", {"fields": {**HOT, "zip": zip_code}})
        assert r["office"]["id"] == office
        office_reps = {r.id for o in mortgage.routing.offices if o.id == office for r in o.reps}
        assert ctx.session.rep_id in office_reps


def test_the_knowledge_base_answers_mortgage_questions_with_sources(mortgage):
    _, reg = ctx_for(mortgage)
    hit = reg.call("search_knowledge", {"query": "do you charge an application fee"})
    assert hit["found"] and hit["hits"][0]["source"] == "knowledge/rates_and_fees.md"
    assert "do not charge an application fee" in hit["hits"][0]["text"]
    down = reg.call("search_knowledge", {"query": "how much down payment for an FHA loan"})
    assert (
        down["hits"][0]["source"] == "knowledge/programs.md" and "3.5%" in down["hits"][0]["text"]
    )
    assert not reg.call("search_knowledge", {"query": "do you install solar panels on roofs"})[
        "found"
    ]


def test_rate_quotes_and_approval_promises_are_blocked_for_this_company(mortgage):
    ctx, reg = ctx_for(mortgage)
    for body in (
        "Today's 30-year fixed rate is 6.5%.",
        "We can get you a 4.9% APR.",
        "I guarantee you'll be approved.",
        "Your payment would be about $2,100 a month.",
    ):
        assert reg.call("send_message", {"body": body})["blocked"] == "unsupported_claim", body
    ok = reg.call(
        "send_message", {"body": "FHA loans start at 3.5% down with a 580 credit score or higher."}
    )
    assert ok["sent"]


def test_conversations_never_leak_between_companies(tmp_path):
    from fastapi.testclient import TestClient

    from leadagent.llm import ScriptedLLM
    from leadagent.server import Settings, create_app

    llm = ScriptedLLM(
        [
            reply(tool_use("update_crm", summary="Solar lead.")),
            reply(text("ok")),
            reply(tool_use("check_existing_contact")),
            reply(text("ok")),
        ]
    )
    app = create_app(
        Settings(
            database_path=str(tmp_path / "x.db"), adapter_env={}, default_company="sunrise_solar"
        ),
        llm_factory=lambda: llm,
        clock=FixedClock(BUSINESS_TIME),
        load_env=False,
        flush_interval=3600,
    )
    with TestClient(app) as client:
        client.post("/api/leads", json={**FORM, "company": "sunrise_solar"})
        lead = client.post("/api/leads", json={**FORM, "company": SLUG}).json()["lead_id"]
        d = client.get(f"/api/leads/{lead}").json()
        assert d["summary"]["company"] == SLUG
        assert d["tool_calls"][0]["result"] == {"exists": False}, (
            "the other company's CRM must not match"
        )
        assert client.get("/api/leads", params={"company": SLUG}).json()["leads"][0]["id"] == lead
        cfgs = {c: client.get(f"/api/companies/{c}/config").json() for c in ("sunrise_solar", SLUG)}
        assert (
            cfgs[SLUG]["brand_color"] == "#1E3A8A"
            and cfgs["sunrise_solar"]["brand_color"] == "#F59E0B"
        )
        assert (
            cfgs[SLUG]["appointment_minutes"] == 30
            and cfgs[SLUG]["slack_channel"] == "#mortgage-leads"
        )
        assert client.get(cfgs[SLUG]["logo_url"]).headers["content-type"].startswith("image/svg")
        names = {c["name"] for c in client.get("/api/companies").json()["companies"]}
        assert names == {"Sunrise Solar", "First Lakes Mortgage"}
