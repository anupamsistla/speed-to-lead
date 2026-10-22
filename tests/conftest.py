from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from leadagent.adapters import build_adapters
from leadagent.clock import FixedClock
from leadagent.config import load_company
from leadagent.llm import ScriptedLLM
from leadagent.models import Lead
from leadagent.retrieval import BM25Retriever
from leadagent.routing import Router
from leadagent.server import Settings, create_app
from leadagent.session import LeadSession
from leadagent.tools import ToolContext, ToolRegistry

SLUG = "sunrise_solar"
DENVER = ZoneInfo("America/Denver")
# Tuesday 10:00 local, inside business hours and outside quiet hours
BUSINESS_TIME = datetime(2026, 10, 27, 10, 0, tzinfo=DENVER)
NIGHT_TIME = datetime(2026, 10, 27, 22, 30, tzinfo=DENVER)


@pytest.fixture(scope="session")
def bundle():
    return load_company(SLUG)


@pytest.fixture
def clock():
    return FixedClock(BUSINESS_TIME)


@pytest.fixture
def make_ctx(bundle, clock):
    """Factory: build a fresh ToolContext (mock adapters) for a lead."""

    def _make(**lead_kwargs) -> tuple[ToolContext, ToolRegistry]:
        lead_kwargs.setdefault("id", "lead1")
        lead_kwargs.setdefault("name", "Jamie Rivera")
        lead_kwargs.setdefault("phone", "+13035550142")
        lead_kwargs.setdefault("created_at", clock.now())
        retriever = BM25Retriever()
        retriever.index(bundle.knowledge)
        calls: list = []
        ctx = ToolContext(
            bundle=bundle,
            session=LeadSession(lead=Lead(**lead_kwargs)),
            adapters=build_adapters(bundle, clock, env={}),
            retriever=retriever,
            router=Router(bundle.routing),
            clock=clock,
            record=calls.append,
        )
        ctx.calls = calls  # type: ignore[attr-defined]
        return ctx, ToolRegistry(ctx)

    return _make


HOT_FIELDS = {
    "zip": "80205",
    "homeowner": "owner",
    "monthly_bill": "$250",
    "roof_type": "asphalt shingle",
    "timeline": "asap",
}


@pytest.fixture
def make_agent(bundle, clock):
    """Factory: a LeadAgent on mock adapters driven by a ScriptedLLM."""
    from leadagent.agent import LeadAgent
    from leadagent.llm import ScriptedLLM

    def _make(steps=None, **kwargs):
        llm = ScriptedLLM(steps)
        adapters = build_adapters(bundle, clock, env={})
        tool_calls: list = []
        agent = LeadAgent(bundle, adapters, llm, clock, record_tool=tool_calls.append, **kwargs)
        agent.tool_calls = tool_calls  # type: ignore[attr-defined]
        return agent, llm, adapters

    return _make


@pytest.fixture
def new_lead(clock):
    def _lead(**kw):
        kw.setdefault("id", "lead1")
        kw.setdefault("name", "Jamie Rivera")
        kw.setdefault("phone", "+13035550142")
        kw.setdefault("source", "web_form")
        kw.setdefault("message", "I'm interested in solar for my house.")
        kw.setdefault("created_at", clock.now())
        return Lead(**kw)

    return _lead


FORM = {
    "name": "Jamie Rivera",
    "phone": "+13035550142",
    "message": "Own my home in 80205, bill is $250, asphalt roof, want it ASAP",
}


@pytest.fixture
def make_app(tmp_path):
    """Factory returning (client, llm, app). The database file survives across calls."""
    clients: list[TestClient] = []

    def _make(steps=None, *, clock=None, secret=None, db=None, llm=None):
        llm = llm or ScriptedLLM(steps)
        settings = Settings(
            database_path=str(db or tmp_path / "t.db"),
            webhook_secret=secret,
            adapter_env={},
        )
        app = create_app(
            settings,
            llm_factory=lambda: llm,
            clock=clock or FixedClock(BUSINESS_TIME),
            load_env=False,
            flush_interval=3600,
        )
        client = TestClient(app)
        client.__enter__()
        clients.append(client)
        return client, llm, app

    yield _make
    for c in clients:
        c.__exit__(None, None, None)
