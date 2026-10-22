"""Backend for the Playwright smoke test.

The real API, tools, guardrails, persistence and mock adapters, with a rule-based stand-in for
the model, so the browser test is deterministic and needs no network or API key.

    python scripts/e2e_server.py --port 8100
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from leadagent.clock import OffsetClock  # noqa: E402
from leadagent.llm import LLMResponse, reply, text, tool_use  # noqa: E402
from leadagent.server import Settings, create_app  # noqa: E402

ANSWERS = {
    "zip": "80205",
    "homeowner": "owner",
    "monthly_bill": 250,
    "roof_type": "asphalt shingle",
    "timeline": "asap",
}


def _calls(messages: list[dict[str, Any]], start: int) -> list[str]:
    return [
        b["name"]
        for m in messages[start:]
        if m["role"] == "assistant"
        for b in m["content"]
        if b["type"] == "tool_use"
    ]


def _results(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for m in reversed(messages):
        if m["role"] == "user" and isinstance(m["content"], list):
            out += [
                json.loads(b["content"]) for b in m["content"] if b.get("type") == "tool_result"
            ]
    return out


class RuleBasedLLM:
    """Decides the next step from what has already happened this turn."""

    def create(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict]
    ) -> LLMResponse:
        inbound = max(
            i
            for i, m in enumerate(messages)
            if m["role"] == "user" and m["content"] and m["content"][0].get("type") == "text"
        )
        done = _calls(messages, inbound)
        slots = next((r["slots"] for r in _results(messages) if r.get("slots")), [])

        if inbound == 0:  # first message from the lead
            if not done:
                return reply(
                    tool_use("check_existing_contact"),
                    tool_use(
                        "send_message",
                        body="Hi, thanks for reaching out! I'll get you set up. Your Team",
                    ),
                    tool_use("score_lead", fields=ANSWERS),
                )
            if "update_crm" not in done:
                return reply(
                    tool_use("update_crm", summary="Owner with a $250 bill who wants it ASAP."),
                    tool_use("notify_rep", note="Hot lead, wants to move fast"),
                    tool_use("get_slots"),
                )
            if done.count("send_message") < 2 and slots:
                labels = " or ".join(s["label"] for s in slots[:2])
                return reply(tool_use("send_message", body=f"I can do {labels}. Which works?"))
            return reply(text("done"))

        if "book_appointment" not in done and slots:  # the lead picked a time
            return reply(tool_use("book_appointment", slot_id=slots[0]["slot_id"]))
        if "send_message" not in done and "book_appointment" in done:
            return reply(
                tool_use("send_message", body="You're booked! A rep will see you then."),
                tool_use("update_crm", summary="Booked.", stage_event="booked"),
                tool_use("notify_rep"),
            )
        return reply(text("done"))


def business_hours_now(tz: str = "America/Denver") -> datetime:
    day = datetime.now(ZoneInfo(tz))
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day.replace(hour=10, minute=0, second=0, microsecond=0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8100)
    args = parser.parse_args()

    clock = OffsetClock()
    clock.set(business_hours_now())
    db = Path(tempfile.mkdtemp()) / "e2e.db"
    app = create_app(
        Settings(database_path=str(db), adapter_env={}),
        llm_factory=RuleBasedLLM,
        clock=clock,
        load_env=False,
    )
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
