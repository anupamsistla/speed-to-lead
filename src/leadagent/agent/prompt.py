"""Build the system prompt from the shared template plus company.yaml and qualification.yaml."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from leadagent.config.schemas import WEEKDAYS, CompanyBundle
from leadagent.guardrails import in_quiet_hours
from leadagent.session import LeadSession

TEMPLATE_PATH = Path(__file__).with_name("system_prompt.md")
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
_DAY_NAMES = dict(zip(WEEKDAYS, ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"), strict=True))


def _hours(bundle: CompanyBundle) -> str:
    parts = []
    for day in WEEKDAYS:
        window = bundle.company.business_hours.window(day)
        if window:
            parts.append(f"{_DAY_NAMES[day]} {window[0]}-{window[1]}")
    return ", ".join(parts) or "not set"


def _fields(bundle: CompanyBundle) -> str:
    lines = []
    for f in bundle.qualification.required_fields:
        opts = f" (one of: {', '.join(f.options)})" if f.options else ""
        lines.append(f'- {f.key} [{f.type}]{opts}. Ask: "{f.question}"')
    return "\n".join(lines)


def _disqualify(bundle: CompanyBundle) -> str:
    rules = [f"  - {r.name}: {r.reason}" for r in bundle.qualification.disqualify_if]
    rules.append("  - out_of_area: the zip is outside the service area.")
    return "\n".join(rules)


def build_system_prompt(bundle: CompanyBundle) -> str:
    c = bundle.company
    values = {
        "company_name": c.name,
        "company_description": " ".join(c.description.split()),
        "tone": " ".join(c.tone.split()),
        "reply_signature": c.reply_signature,
        "timezone": c.timezone,
        "business_hours": _hours(bundle),
        "quiet_hours": f"{c.quiet_hours.start} to {c.quiet_hours.end}",
        "appointment_kind": bundle.routing.appointment.kind,
        "appointment_minutes": str(bundle.routing.appointment.duration_minutes),
        "fields": _fields(bundle),
        "disqualify_rules": _disqualify(bundle),
        "hot_threshold": str(bundle.qualification.hot_lead_threshold),
    }
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    unknown = set(_PLACEHOLDER.findall(template)) - values.keys()
    if unknown:
        raise ValueError(f"system prompt template uses unknown placeholders: {sorted(unknown)}")
    return _PLACEHOLDER.sub(lambda m: values[m.group(1)], template)


def local_time_note(bundle: CompanyBundle, now: datetime) -> str:
    local = now.astimezone(ZoneInfo(bundle.company.timezone))
    day = WEEKDAYS[local.weekday()]
    window = bundle.company.business_hours.window(day)
    open_now = bool(window and window[0] <= local.strftime("%H:%M") < window[1])
    state = "office is open" if open_now else "office is closed"
    if in_quiet_hours(bundle.company, now):
        state += ", quiet hours (messages will be queued until morning)"
    return f"{local:%A %Y-%m-%d %H:%M} {bundle.company.timezone} ({state})"


def first_turn_context(session: LeadSession, bundle: CompanyBundle, now: datetime) -> str:
    lead = session.lead
    rows = {
        "source": lead.source,
        "name": lead.name or "unknown",
        "phone": lead.phone or "unknown",
        "email": lead.email or "unknown",
        "local_time": local_time_note(bundle, now),
    }
    body = "\n".join(f"{k}: {v}" for k, v in rows.items())
    return f"<lead_context>\n{body}\n</lead_context>"
