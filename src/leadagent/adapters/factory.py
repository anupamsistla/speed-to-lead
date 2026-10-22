"""Build the adapter set from env vars. Defaults to mocks for everything."""

from __future__ import annotations

import os
from collections.abc import Mapping

from leadagent.adapters.base import Adapters
from leadagent.adapters.hubspot import HubSpotCRM
from leadagent.adapters.mock import MockCalendar, MockChannel, MockCRM, MockNotifier
from leadagent.adapters.slack import SlackNotifier
from leadagent.adapters.stubs import GoogleCalendar, TwilioChannel
from leadagent.clock import Clock
from leadagent.config.schemas import CompanyBundle


def _choice(env: Mapping[str, str], key: str, allowed: set[str]) -> str:
    value = (env.get(key) or "mock").strip().lower()
    if value not in allowed:
        raise ValueError(f"{key}={value!r} is not one of {sorted(allowed)}")
    return value


def build_adapters(
    bundle: CompanyBundle,
    clock: Clock,
    env: Mapping[str, str] | None = None,
    *,
    mock_crm_path: str = ":memory:",
    mock_crm_table: str = "crm_contacts",
) -> Adapters:
    env = os.environ if env is None else env

    channel_kind = _choice(env, "CHANNEL_ADAPTER", {"mock", "twilio"})
    channel = (
        TwilioChannel(
            env.get("TWILIO_ACCOUNT_SID", ""),
            env.get("TWILIO_AUTH_TOKEN", ""),
            env.get("TWILIO_FROM_NUMBER", ""),
        )
        if channel_kind == "twilio"
        else MockChannel(clock)
    )

    crm_kind = _choice(env, "CRM_ADAPTER", {"mock", "hubspot"})
    if crm_kind == "hubspot":
        crm = HubSpotCRM(
            env.get("HUBSPOT_TOKEN", ""),
            mapped_properties=list(bundle.crm_mapping.field_map.values()),
        )
    else:
        crm = MockCRM(mock_crm_path, mock_crm_table)

    calendar_kind = _choice(env, "CALENDAR_ADAPTER", {"mock", "google"})
    if calendar_kind == "google":
        calendar = GoogleCalendar()
    else:
        rep_hours = {r.id: r.business_hours for o in bundle.routing.offices for r in o.reps}
        calendar = MockCalendar(rep_hours, bundle.company.timezone, clock)

    notifier_kind = _choice(env, "NOTIFIER_ADAPTER", {"mock", "slack"})
    notifier = (
        SlackNotifier(env.get("SLACK_WEBHOOK_URL", ""))
        if notifier_kind == "slack"
        else MockNotifier()
    )

    return Adapters(channel=channel, crm=crm, calendar=calendar, notifier=notifier)
