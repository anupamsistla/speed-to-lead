from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from leadagent.adapters import build_adapters
from leadagent.clock import FixedClock
from leadagent.config import load_company
from leadagent.models import Lead
from leadagent.retrieval import BM25Retriever
from leadagent.routing import Router
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
