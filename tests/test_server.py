"""API tests: intake, lead detail, persistence, SSE history, webhooks, clock, takeover."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from leadagent.adapters.mock import MockCRM
from leadagent.clock import FixedClock, OffsetClock
from leadagent.llm import ScriptedLLM, reply, text, tool_use
from leadagent.server import Settings, create_app
from leadagent.server.events import EventBus
from leadagent.server.logging_setup import JsonFormatter
from leadagent.server.store import Store
from tests.conftest import BUSINESS_TIME, FORM, HOT_FIELDS, NIGHT_TIME
from tests.test_agent import book_first_slot, offer_slots

DEN = ZoneInfo("America/Denver")


FIRST_TURN = [
    reply(
        tool_use("check_existing_contact"),
        tool_use("send_message", body="Hi Jamie, thanks for reaching out! Sunrise Solar Team"),
        tool_use("score_lead", fields=HOT_FIELDS),
    ),
    reply(
        tool_use("update_crm", summary="Owner, $250 bill, ASAP."),
        tool_use("notify_rep", note="Hot lead"),
        tool_use("get_slots"),
    ),
    offer_slots,
    reply(text("done")),
]


# ------------------------------------------------------------------ system + config
def test_health_reports_adapters_and_llm(make_app):
    client, _, _ = make_app()
    h = client.get("/api/health").json()
    assert h["ok"] and h["llm"] == "ready" and h["model"] == "claude-sonnet-5-5"
    assert h["adapters"] == {
        "channel": "mock",
        "crm": "mock",
        "calendar": "mock",
        "notifier": "mock",
    }


def test_companies_and_runtime_branding(make_app):
    client, _, _ = make_app()
    data = client.get("/api/companies").json()
    assert data["default"] and any(c["slug"] == data["default"] for c in data["companies"])
    slug = data["default"]
    cfg = client.get(f"/api/companies/{slug}/config").json()
    assert cfg["brand_color"] == "#F59E0B" and cfg["name"] == "Sunrise Solar"
    assert cfg["logo_url"] == f"/api/companies/{slug}/logo"
    assert [f["key"] for f in cfg["fields"]][0] == "zip" and len(cfg["offices"]) == 3
    assert "email" not in json.dumps(cfg)  # no rep contact details leak to the browser
    logo = client.get(cfg["logo_url"])
    assert logo.status_code == 200 and logo.headers["content-type"].startswith("image/svg")


def test_unknown_company_is_404(make_app):
    client, _, _ = make_app()
    assert client.get("/api/companies/nope/config").status_code == 404
    assert client.get("/api/companies/nope/logo").status_code == 404
    assert client.post("/api/leads", json={**FORM, "company": "nope"}).status_code == 404


# ---------------------------------------------------------------- lead lifecycle
def test_submit_lead_and_read_back_everything(make_app):
    client, llm, _ = make_app(list(FIRST_TURN))
    r = client.post("/api/leads", json=FORM)
    assert r.status_code == 202
    lead_id = r.json()["lead_id"]

    d = client.get(f"/api/leads/{lead_id}").json()
    assert d["summary"]["status"] == "in_progress" and d["summary"]["tier"] == "hot"
    assert d["summary"]["first_response_seconds"] == 0
    assert [m["direction"] for m in d["messages"]][:2] == ["inbound", "outbound"]
    assert d["messages"][0]["sender"] == "lead" and d["messages"][1]["sender"] == "agent"
    assert d["answers"]["zip"] == "80205" and d["missing_fields"] == []
    assert d["score"]["score"] == 90 and sum(i["points"] for i in d["score"]["breakdown"]) == 90
    assert (
        d["routing"]["office_name"] == "Denver Office" and d["routing"]["rep_name"] == "Maya Ortiz"
    )
    assert d["crm"]["stage"] == "New Lead" and d["crm"]["synced"]
    assert d["crm"]["properties"]["homeowner_status"] == "owner"
    assert d["crm"]["properties"]["conversation_summary"].startswith("Owner")
    assert [n["kind"] for n in d["notifications"]] == ["hot_lead"]
    assert [t["name"] for t in d["tool_calls"]][:3] == [
        "check_existing_contact",
        "send_message",
        "score_lead",
    ]
    assert all(t["latency_ms"] >= 0 for t in d["tool_calls"])
    assert llm.calls == 4


def test_full_flow_to_booked_appointment(make_app):
    client, llm, _ = make_app(list(FIRST_TURN))
    lead_id = client.post("/api/leads", json=FORM).json()["lead_id"]
    llm.steps = [
        book_first_slot,
        reply(
            tool_use(
                "send_message", body="You're booked! Maya from our Denver office will see you."
            ),
            tool_use("update_crm", summary="Hot owner lead. Booked.", stage_event="booked"),
            tool_use("notify_rep"),
        ),
        reply(text("done")),
    ]
    assert (
        client.post(f"/api/leads/{lead_id}/messages", json={"text": "The first one"}).status_code
        == 202
    )

    d = client.get(f"/api/leads/{lead_id}").json()
    assert d["summary"]["status"] == "booked" and d["booking"]["office_name"] == "Denver Office"
    assert d["crm"]["stage"] == "Appointment Booked"
    assert [n["kind"] for n in d["notifications"]] == ["hot_lead", "booked"]
    assert d["crm"]["properties"]["consultation_time"].startswith("2026-10-27")
    assert d["flags"] == []

    listing = client.get("/api/leads").json()["leads"]
    assert [x["id"] for x in listing] == [lead_id] and listing[0]["booked"]


def test_input_validation(make_app):
    client, _, _ = make_app()
    assert client.post("/api/leads", json={"message": "hi"}).status_code == 422
    assert client.post("/api/leads", json={"source": "text", "email": "a@b.co"}).status_code == 422
    assert (
        client.post("/api/leads", json={"source": "text", "phone": "1", "message": " "}).status_code
        == 422
    )
    assert client.get("/api/leads/ld_nope").status_code == 404
    assert client.post("/api/leads/ld_nope/messages", json={"text": "hi"}).status_code == 404


def test_state_survives_a_restart(make_app, tmp_path):
    client, llm, _ = make_app(list(FIRST_TURN))
    lead_id = client.post("/api/leads", json=FORM).json()["lead_id"]
    before = client.get(f"/api/leads/{lead_id}").json()

    client2, llm2, _ = make_app(
        [book_first_slot, reply(text("done"))],
        clock=FixedClock(BUSINESS_TIME),
        db=tmp_path / "t.db",
    )
    after = client2.get(f"/api/leads/{lead_id}").json()
    assert after["messages"] == before["messages"] and after["score"] == before["score"]
    assert len(after["tool_calls"]) == len(before["tool_calls"])
    # the restored conversation continues, offered slots included
    client2.post(f"/api/leads/{lead_id}/messages", json={"text": "first one"})
    assert client2.get(f"/api/leads/{lead_id}").json()["booking"]


def test_restart_keeps_booked_slots_taken(make_app, tmp_path):
    client, llm, _ = make_app(list(FIRST_TURN))
    lead_id = client.post("/api/leads", json=FORM).json()["lead_id"]
    llm.steps = [book_first_slot, reply(text("."))]
    client.post(f"/api/leads/{lead_id}/messages", json={"text": "first"})
    booked = client.get(f"/api/leads/{lead_id}").json()["booking"]

    client2, llm2, app2 = make_app(db=tmp_path / "t.db")
    rt = app2.state.manager.get(client2.get("/api/companies").json()["default"])
    cal = rt.adapters.calendar
    start = datetime.fromisoformat(booked["start"])
    assert not cal.is_free(booked["rep_id"], start, 60)


# ----------------------------------------------------------------- events + SSE
def test_event_history_and_sse_replay_agree(make_app):
    client, _, _ = make_app(list(FIRST_TURN))
    lead_id = client.post("/api/leads", json=FORM).json()["lead_id"]

    hist = client.get(f"/api/leads/{lead_id}/events/history").json()["events"]
    ids = [e["id"] for e in hist]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    types = [e["type"] for e in hist]
    assert types[0] == "lead_created" and types[-1] == "turn_done"
    assert {"message", "tool_call", "state", "first_response", "notification"} <= set(types)
    fr = next(e for e in hist if e["type"] == "first_response")
    assert fr["data"]["seconds"] == 0
    # the first reply is announced before the slower tool calls finish
    assert types.index("first_response") < types.index("notification")

    sse = client.get(f"/api/leads/{lead_id}/events?follow=false")
    assert sse.headers["content-type"].startswith("text/event-stream")
    parsed = [
        json.loads(line.removeprefix("data: "))
        for line in sse.text.splitlines()
        if line.startswith("data: ")
    ]
    assert [e["id"] for e in parsed] == ids
    assert sse.text.startswith(f"id: {ids[0]}\nevent: lead_created\ndata: ")
    assert "\nevent: tool_call\n" in sse.text

    resumed = client.get(f"/api/leads/{lead_id}/events/history?after={ids[3]}").json()["events"]
    assert [e["id"] for e in resumed] == ids[4:]
    via_header = client.get(
        f"/api/leads/{lead_id}/events?follow=false", headers={"Last-Event-ID": str(ids[-3])}
    )
    assert via_header.text.count("event: ") == 2


def test_company_wide_stream_is_scoped_to_the_company(make_app):
    client, _, _ = make_app(list(FIRST_TURN))
    client.post("/api/leads", json=FORM)
    slug = client.get("/api/companies").json()["default"]
    assert "event: lead_created" in client.get(f"/api/events?company={slug}&follow=false").text
    assert client.get("/api/events?company=other&follow=false").text == ""


def test_bus_delivers_live_events_across_threads(tmp_path):
    store = Store(":memory:")
    bus = EventBus(store)
    now = BUSINESS_TIME

    async def scenario():
        mine = bus.subscribe(lead_id="a")
        everyone = bus.subscribe(company="c")
        other = bus.subscribe(lead_id="zzz")
        t = threading.Thread(target=lambda: bus.publish("c", "a", "message", {"n": 1}, now))
        t.start()
        got = await asyncio.wait_for(mine.queue.get(), 2)
        got_all = await asyncio.wait_for(everyone.queue.get(), 2)
        t.join()
        assert got.id == got_all.id >= 1 and got.data == {"n": 1}
        assert other.queue.empty()
        for s in (mine, everyone, other):
            bus.unsubscribe(s)
        assert bus.subscriber_count == 0

    asyncio.run(scenario())


# --------------------------------------------------------------------- webhooks
def test_webhook_secret_is_enforced(make_app):
    client, _, _ = make_app([reply(text("hi"))], secret="s3cret")
    body = {"name": "Jamie", "phone": "+13035550142", "message": "solar please"}
    assert client.post("/api/intake/web-form", json=body).status_code == 401
    bad = client.post("/api/intake/web-form", json=body, headers={"X-Webhook-Secret": "nope"})
    assert bad.status_code == 401
    ok = client.post("/api/intake/web-form", json=body, headers={"X-Webhook-Secret": "s3cret"})
    assert ok.status_code == 202
    # the direct UI endpoint is not a webhook and stays open for the demo
    assert client.post("/api/leads", json=FORM).status_code == 202


def test_web_form_missed_call_and_sms_webhooks(make_app):
    client, llm, _ = make_app([reply(text("hi"))] * 6)
    web = client.post(
        "/api/intake/web-form", json={"email": "a@b.co", "message": "info please", "consent": True}
    )
    assert (
        client.get(f"/api/leads/{web.json()['lead_id']}").json()["summary"]["consent"] == "opted_in"
    )

    call = client.post("/api/intake/missed-call", json={"from": "+13035559999"}).json()
    d = client.get(f"/api/leads/{call['lead_id']}").json()
    assert d["lead"]["source"] == "missed_call" and d["summary"]["consent"] == "unknown"
    assert d["messages"][0]["direction"] == "outbound"  # holding reply: nothing inbound to quote

    sms = client.post(
        "/api/intake/sms", json={"from": "(720) 555-0101", "body": "hi, solar?"}
    ).json()
    again = client.post(
        "/api/intake/sms", json={"from": "+1 720 555 0101", "body": "my zip is 80205"}
    ).json()
    assert again["lead_id"] == sms["lead_id"]  # same number continues the same conversation
    detail = client.get(f"/api/leads/{sms['lead_id']}").json()
    assert detail["summary"]["consent"] == "opted_in" and detail["lead"]["source"] == "text"
    assert [m["body"] for m in detail["messages"] if m["direction"] == "inbound"] == [
        "hi, solar?",
        "my zip is 80205",
    ]
    assert client.post("/api/intake/sms", json={"from": "+1", "body": ""}).status_code == 422
    assert client.post("/api/intake/web-form", json={"message": "x"}).status_code == 422


def test_stop_by_text_is_recorded_and_silent(make_app):
    client, llm, _ = make_app()
    lead_id = client.post("/api/intake/sms", json={"from": "+17205550101", "body": "STOP"}).json()[
        "lead_id"
    ]
    d = client.get(f"/api/leads/{lead_id}").json()
    assert d["summary"]["status"] == "opted_out" and d["summary"]["consent"] == "opted_out"
    assert llm.calls == 0 and len(d["messages"]) == 2  # STOP, then the unsubscribe confirmation


# -------------------------------------------------------------------- no model
def test_without_an_api_key_the_server_explains_itself(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    app = create_app(Settings(database_path=str(tmp_path / "x.db"), adapter_env={}), load_env=False)
    with TestClient(app) as client:
        assert client.get("/api/health").json()["llm"] == "missing_api_key"
        r = client.post("/api/leads", json=FORM)
        assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.json()["detail"]
        assert client.get("/api/leads").json() == {"leads": []}  # reading needs no model


# ------------------------------------------------------- quiet hours via the clock
def test_simulated_clock_defers_and_flush_delivers(make_app):
    clock = OffsetClock()
    client, _, app = make_app(
        [
            reply(tool_use("send_message", body="Hi Jamie, thanks for reaching out!")),
            reply(text(".")),
        ],
        clock=clock,
    )
    r = client.put("/api/clock", json={"now": NIGHT_TIME.isoformat()})
    assert r.json()["simulated"] is True
    lead_id = client.post("/api/leads", json=FORM).json()["lead_id"]

    d = client.get(f"/api/leads/{lead_id}").json()
    assert len(d["deferred"]) == 1 and d["summary"]["first_response_seconds"] is None
    assert [m for m in d["messages"] if m["direction"] == "outbound"] == []
    kinds = [e["type"] for e in client.get(f"/api/leads/{lead_id}/events/history").json()["events"]]
    assert "deferred" in kinds and "first_response" not in kinds

    assert app.state.manager.flush_all() == 0  # still night
    morning = datetime(2026, 10, 28, 8, 5, tzinfo=DEN)
    client.put("/api/clock", json={"now": morning.isoformat()})
    assert app.state.manager.flush_all() == 1

    d = client.get(f"/api/leads/{lead_id}").json()
    assert d["deferred"] == [] and d["messages"][-1]["body"].startswith("Hi Jamie")
    assert 9 * 3600 < d["summary"]["first_response_seconds"] < 10 * 3600
    kinds = [e["type"] for e in client.get(f"/api/leads/{lead_id}/events/history").json()["events"]]
    assert kinds.count("first_response") == 1

    assert client.put("/api/clock", json={"now": None}).json()["simulated"] is False
    assert client.put("/api/clock", json={"now": "2026-10-28T08:05:00"}).status_code == 422


# -------------------------------------------------------------- human takeover
def test_takeover_silences_the_agent_and_human_messages_are_labelled(make_app):
    client, llm, _ = make_app(list(FIRST_TURN))
    lead_id = client.post("/api/leads", json=FORM).json()["lead_id"]
    calls = llm.calls

    t = client.post(f"/api/leads/{lead_id}/takeover").json()
    assert t["status"] == "human"
    client.post(f"/api/leads/{lead_id}/messages", json={"text": "one more question"})
    assert llm.calls == calls

    m = client.post(
        f"/api/leads/{lead_id}/human-message", json={"text": "Hi, this is Maya."}
    ).json()
    assert m["sender"] == "human" and m["direction"] == "outbound"
    d = client.get(f"/api/leads/{lead_id}").json()
    assert (
        d["messages"][-1]["sender"] == "human" and d["messages"][-2]["body"] == "one more question"
    )
    events = client.get(f"/api/leads/{lead_id}/events/history").json()["events"]
    human_events = [e for e in events if e["type"] == "message" and e["data"]["sender"] == "human"]
    assert len(human_events) == 1


def test_escalation_is_visible_in_the_api(make_app):
    client, _, _ = make_app([reply(text("on it"))])
    lead_id = client.post(
        "/api/leads", json={**FORM, "message": "I want to talk to a real person"}
    ).json()["lead_id"]
    d = client.get(f"/api/leads/{lead_id}").json()
    assert d["summary"]["status"] == "escalated"
    assert [n["kind"] for n in d["notifications"]] == ["escalation"]
    assert "backstop:escalate" in d["flags"]


# ---------------------------------------------------------- persistence details
def test_store_records_scores_turns_and_calls(make_app, tmp_path):
    client, llm, app = make_app(list(FIRST_TURN))
    lead_id = client.post("/api/leads", json=FORM).json()["lead_id"]
    store: Store = app.state.store
    hist = store.score_history(lead_id)
    assert [h["score"] for h in hist] == [90] and hist[0]["tier"] == "hot"
    [turn] = store.turns(lead_id)
    assert turn["trigger"] == "lead" and turn["duration_ms"] >= 0
    assert [c.name for c in store.tool_calls(lead_id)][0] == "check_existing_contact"
    row = store.lead_row(lead_id)
    assert row["tier"] == "hot" and row["first_response_seconds"] == 0


def test_agent_crash_is_contained(make_app):
    class Boom(ScriptedLLM):
        def create(self, **kw):  # a bug, not an API error the agent already handles
            raise KeyboardInterrupt if False else AttributeError("bug")

    client, _, _ = make_app(llm=Boom())
    lead_id = client.post("/api/leads", json=FORM).json()["lead_id"]
    d = client.get(f"/api/leads/{lead_id}").json()
    assert d["summary"]["status"] == "escalated"  # outage path escalates instead of silence
    assert "llm_error" in d["flags"]


# -------------------------------------------------------------------- contract
def test_openapi_exposes_the_types_the_ui_needs(make_app):
    client, _, _ = make_app()
    spec = client.get("/openapi.json").json()
    schemas = spec["components"]["schemas"]
    for name in (
        "LeadDetail",
        "LeadSummary",
        "StreamEvent",
        "CompanyPublicConfig",
        "Score",
        "Booking",
        "ToolCall",
        "Message",
        "Notification",
        "LeadIn",
    ):
        assert name in schemas, name
    assert set(schemas["StreamEvent"]["properties"]["type"]["enum"]) >= {
        "tool_call",
        "message",
        "first_response",
        "state",
    }
    assert "/api/leads/{lead_id}/events" in spec["paths"]


# ------------------------------------------------------------ isolation + logging
def test_mock_crm_tables_are_isolated_per_company(tmp_path):
    path = str(tmp_path / "crm.db")
    a, b = MockCRM(path, "crm_a"), MockCRM(path, "crm_b")
    a.seed_contact(name="Only in A", phone="3035550142")
    assert a.find_contact(phone="3035550142", email=None)
    assert b.find_contact(phone="3035550142", email=None) is None
    with pytest.raises(ValueError):
        MockCRM(path, "x; drop table y")


def test_concurrent_bookings_never_share_a_slot(bundle, clock):
    from leadagent.adapters.mock import MockCalendar
    from leadagent.models import Lead

    hours = {r.id: r.business_hours for o in bundle.routing.offices for r in o.reps}
    cal = MockCalendar(hours, bundle.company.timezone, clock)
    slot = cal.get_slots(
        ["maya_ortiz"],
        start=clock.now(),
        end=clock.now().replace(hour=23),
        duration_minutes=60,
    )[0]
    results: list[bool] = []

    def attempt(i: int):
        lead = Lead(id=f"l{i}", created_at=clock.now())
        try:
            cal.book(slot=slot, lead=lead, office_id="d", office_name="D", rep_name="M", kind="k")
            results.append(True)
        except ValueError:
            results.append(False)

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(25)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count(True) == 1


def test_structured_log_lines_are_json_with_extras():
    rec = logging.LogRecord("leadagent.x", logging.INFO, __file__, 1, "tool_call", (), None)
    rec.lead_id, rec.latency_ms = "ld_1", 12.5
    out = json.loads(JsonFormatter().format(rec))
    assert out["msg"] == "tool_call" and out["lead_id"] == "ld_1" and out["latency_ms"] == 12.5
    assert out["level"] == "info" and out["ts"].endswith("+00:00")
