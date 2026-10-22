"""Scenario loading and replay, clock presets, and the exported OpenAPI contract."""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import yaml

from leadagent.llm import reply, text, tool_use
from leadagent.scenarios import Scenario, load_scenario, load_scenarios
from tests.conftest import FORM, HOT_FIELDS

ROOT = Path(__file__).resolve().parents[1]


def test_saved_scenarios_are_valid_and_belong_to_a_real_company(bundle):
    scenarios = load_scenarios()
    assert len(scenarios) >= 3
    ids = [s.id for s in scenarios]
    assert len(ids) == len(set(ids)), "scenario ids must be unique"
    for s in scenarios:
        assert s.company == bundle.slug or s.company
        assert s.clock is None or s.clock.tzinfo is not None


def test_scenario_schema_rejects_typos():
    with pytest.raises(ValueError):
        Scenario.model_validate(
            {"id": "x", "title": "t", "company": "c", "lead": {"message": "hi"}, "exepct": {}}
        )


def test_lookup_and_company_filter():
    assert load_scenario("hot_lead_books").lead.source == "web_form"
    assert load_scenario("nope") is None
    assert load_scenarios("some_other_company") == []


def test_load_from_custom_directory(tmp_path):
    (tmp_path / "a.yaml").write_text(
        yaml.safe_dump({"id": "a", "title": "A", "company": "c", "lead": {"message": "hi"}})
    )
    assert [s.id for s in load_scenarios(base=tmp_path)] == ["a"]


# --------------------------------------------------------------------- API
def test_scenario_list_endpoint(make_app):
    client, _, _ = make_app()
    data = client.get("/api/scenarios").json()["scenarios"]
    by_id = {s["id"]: s for s in data}
    assert {"hot_lead_books", "out_of_area", "stop_message"} <= set(by_id)
    assert by_id["hot_lead_books"]["followups"] == 1 and by_id["stop_message"]["source"] == "text"
    assert client.get("/api/scenarios?company=nobody").json() == {"scenarios": []}


def test_replay_plays_the_whole_conversation(make_app):
    client, llm, _ = make_app(
        [
            reply(tool_use("check_existing_contact"), tool_use("score_lead", fields=HOT_FIELDS)),
            reply(
                tool_use("update_crm", summary="Hot owner."),
                tool_use("notify_rep"),
                tool_use("get_slots"),
            ),
            reply(tool_use("send_message", body="Free consult today at 12:00 PM or 12:30 PM?")),
            reply(text("ok")),
        ]
    )
    from tests.test_agent import book_first_slot

    r = client.post("/api/scenarios/hot_lead_books/replay?pause=0")
    assert r.status_code == 202
    lead_id = r.json()["lead_id"]
    llm.steps = [book_first_slot, reply(tool_use("send_message", body="Booked!")), reply(text("."))]
    # the replay already ran the follow-up in its background task, so re-read the final state
    d = client.get(f"/api/leads/{lead_id}").json()
    inbound = [m["body"] for m in d["messages"] if m["direction"] == "inbound"]
    assert inbound[0].startswith("Hi, I own my home in 80205")
    assert inbound[1] == "The first time works for me."  # the scripted follow-up was sent
    assert d["lead"]["name"] == "Jamie Rivera"


def test_replay_sets_the_scenario_clock_and_seeds_the_crm(make_app, tmp_path, monkeypatch):
    scen = {
        "id": "existing_contact",
        "title": "Existing contact",
        "company": "sunrise_solar",
        "clock": "2026-10-27T10:00:00-06:00",
        "seed_contacts": [
            {
                "name": "Jamie Rivera",
                "phone": "303-555-0142",
                "fields": {"homeowner": "owner", "roof_type": "tile"},
            }
        ],
        "lead": {
            "name": "Jamie Rivera",
            "phone": "+13035550142",
            "message": "Back again about solar",
        },
    }
    (tmp_path / "s.yaml").write_text(yaml.safe_dump(scen))
    monkeypatch.setenv("SCENARIOS_DIR", str(tmp_path))
    from leadagent.clock import OffsetClock

    client, llm, app = make_app(
        [reply(tool_use("check_existing_contact")), reply(text("ok"))], clock=OffsetClock()
    )
    lead_id = client.post("/api/scenarios/existing_contact/replay?pause=0").json()["lead_id"]
    d = client.get(f"/api/leads/{lead_id}").json()
    assert d["answers"] == {"homeowner": "owner", "roof_type": "tile"}
    assert client.get("/api/clock").json()["simulated"] is True
    assert d["tool_calls"][0]["result"]["exists"] is True


def test_unknown_scenario_is_404(make_app):
    client, _, _ = make_app()
    assert client.post("/api/scenarios/nope/replay").status_code == 404


# -------------------------------------------------------------- clock presets
def test_clock_presets_resolve_in_the_company_timezone(make_app):
    from leadagent.clock import OffsetClock

    client, _, _ = make_app(clock=OffsetClock())
    tz = ZoneInfo("America/Denver")
    biz = client.put("/api/clock", json={"preset": "business_hours"}).json()
    now = datetime.fromisoformat(biz["now"]).astimezone(tz)
    assert biz["simulated"] and now.weekday() < 5 and (now.hour, now.minute) == (10, 0)
    night = client.put("/api/clock", json={"preset": "after_hours"}).json()
    now = datetime.fromisoformat(night["now"]).astimezone(tz)
    assert now.weekday() < 5 and (now.hour, now.minute) == (22, 30)
    assert client.put("/api/clock", json={"preset": "real"}).json()["simulated"] is False
    assert (
        client.put("/api/clock", json={"preset": "business_hours", "company": "nope"}).status_code
        == 404
    )


def test_after_hours_preset_makes_the_agent_hold_its_reply(make_app):
    from leadagent.clock import OffsetClock

    client, _, _ = make_app(
        [reply(tool_use("send_message", body="Hi Jamie!")), reply(text("."))], clock=OffsetClock()
    )
    client.put("/api/clock", json={"preset": "after_hours"})
    d = client.get(f"/api/leads/{client.post('/api/leads', json=FORM).json()['lead_id']}").json()
    assert len(d["deferred"]) == 1 and d["summary"]["first_response_seconds"] is None


# ------------------------------------------------------------------ contract
def test_committed_openapi_matches_the_api():
    """The typed web client is generated from web/openapi.json, so it must not drift."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "export_openapi.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
