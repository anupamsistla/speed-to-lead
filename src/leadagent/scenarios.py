"""Saved scenarios: synthetic leads with expected outcomes.

The same files drive the UI's ScenarioReplay control and the eval harness (`make eval`).
"""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from leadagent.config.loader import REPO_ROOT
from leadagent.models import LeadSource, Tier


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SeedContact(Strict):
    """A contact that already exists in the CRM before the lead arrives."""

    name: str | None = None
    phone: str | None = None
    email: str | None = None
    fields: dict[str, Any] = Field(
        default_factory=dict, description="Internal field keys, mapped to CRM properties on seed."
    )
    stage: str | None = None


class ScenarioLead(Strict):
    name: str | None = None
    phone: str | None = None
    email: str | None = None
    source: LeadSource = "web_form"
    message: str = ""
    consent: bool | None = None


class Expect(Strict):
    """Deterministic assertions. Omitted keys are not checked."""

    qualified: bool | None = None  # False for disqualified, out of area or spam
    tier: Tier | None = None
    office: str | None = None
    booked: bool | None = None
    escalated: bool | None = None
    opted_out: bool | None = None
    closed_reason: str | None = None
    reply_sent: bool | None = None
    crm_written: bool | None = None
    rep_notified: bool | None = None
    flags_include: list[str] = Field(default_factory=list)
    messages_must_not_contain: list[str] = Field(default_factory=list)
    messages_must_contain: list[str] = Field(default_factory=list)


class Scenario(Strict):
    id: str
    title: str
    description: str = ""
    company: str
    clock: datetime | None = Field(
        default=None, description="Simulated 'now' with offset. Omit for business hours default."
    )
    seed_contacts: list[SeedContact] = Field(default_factory=list)
    lead: ScenarioLead
    followups: list[str] = Field(
        default_factory=list, description="Later messages from the lead, sent after each reply."
    )
    expect: Expect = Field(default_factory=Expect)


def scenarios_dir() -> Path:
    return Path(os.environ.get("SCENARIOS_DIR", REPO_ROOT / "evals" / "scenarios"))


def load_scenarios(company: str | None = None, base: Path | None = None) -> list[Scenario]:
    base = base or scenarios_dir()
    out: list[Scenario] = []
    for path in sorted(base.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        scenario = Scenario.model_validate(data)
        if company is None or scenario.company == company:
            out.append(scenario)
    return out


def load_scenario(scenario_id: str, base: Path | None = None) -> Scenario | None:
    return next((s for s in load_scenarios(base=base) if s.id == scenario_id), None)
