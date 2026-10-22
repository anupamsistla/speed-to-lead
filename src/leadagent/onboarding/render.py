"""Render the draft files.

Three kinds of line, so a reviewer always knows what to trust:
  - a verified fact:     value   # source: <page url>
  - a guess:             proposed value   # TODO: guess ...
  - an unknown:          TODO   # TODO: not found on the website ...
The loader refuses to run while any "TODO" remains, so nothing half-reviewed ships.
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Any

from leadagent.config.schemas import CORE_CRM_FIELDS
from leadagent.onboarding.extract import Verified, rule_value

DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
TITLES = {
    "services": "Services",
    "faq": "Frequently asked questions",
    "financing": "Financing and pricing",
    "warranty": "Warranty",
    "process": "How it works",
    "about": "About",
}
CORE_FILES = ("services", "faq", "financing", "warranty")
DEFAULT_PROPERTY = {
    "summary": "conversation_summary",
    "lead_score": "lead_score",
    "score_tier": "lead_tier",
    "assigned_office": "assigned_office",
    "assigned_rep": "assigned_rep",
    "appointment_time": "appointment_time",
    "consent_status": "sms_consent",
    "source": "lead_source",
}


def q(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_") or "office"


def header(url: str, what: str, today: date) -> str:
    # This header must not contain the marker word itself, or a fully reviewed file would
    # still be refused by the loader.
    return (
        f"# {what}. Drafted by scripts/draft_company.py from {url} on {today.isoformat()}.\n"
        '# Lines marked "source:" were verified against the website. Every other value is a guess\n'
        "# or a gap and carries a marker comment. Resolve each marker, then delete its comment.\n"
        "# The agent will not start for this company while any marker remains.\n"
    )


def _num(x: float) -> Any:
    return int(x) if float(x).is_integer() else x


# --------------------------------------------------------------------- company.yaml
def render_company(
    url: str, v: Verified, today: date, brand: tuple[str, str] | None, logo: tuple[str, str] | None
) -> str:
    L = [header(url, "company.yaml", today)]
    name = v.company_name
    L.append(
        f"name: {q(name.value)}  # source: {name.url}"
        if name
        else "name: TODO  # TODO: the company name was not found on the website."
    )
    if v.description:
        text = " ".join(v.description.value.split())
        L.append(f"description: >-\n  {text}\n# source: {v.description.url}")
    else:
        L.append(
            "description: TODO  # TODO: no usable description on the website. One or two factual sentences."
        )
    L.append(
        "tone: >-\n  Friendly, clear and concise. Short text-message replies, no pressure.\n"
        "# TODO: guess. Describe the voice you want. This steers every message the agent writes."
    )
    sig = f"{name.value} Team" if name else "TODO"
    L.append(
        f"reply_signature: {q(sig)}  # TODO: guess. Confirm how the first message should be signed."
        if name
        else 'reply_signature: TODO  # TODO: how the first message is signed, for example "<Company> Team".'
    )
    if v.timezone:
        basis = f" Based on: {v.timezone_basis.quote[:60]!r}." if v.timezone_basis else ""
        L.append(f"timezone: {v.timezone}  # TODO: guess.{basis} Confirm the IANA timezone.")
    else:
        L.append(
            "timezone: TODO  # TODO: IANA timezone such as America/Denver. No address on the site gave a clear answer."
        )

    L.append("business_hours:")
    if v.hours:
        for d in DAYS:
            h = v.hours.get(d)
            if h:
                L.append(f'  {d}: "{h.open}-{h.close}"  # source: {h.url}')
    else:
        L.append(
            '  mon: TODO  # TODO: opening hours were not found on the website. List mon-sun as "HH:MM-HH:MM"; omit closed days.'
        )

    L.append(
        "quiet_hours:  # TODO: default, not from the website. No texts go out in this window. Confirm it fits your region and consent rules.\n"
        '  start: "21:00"\n  end: "08:00"'
    )

    zips = sorted({z.value for z in v.zips} | {z for o in v.offices for z in o.zips})
    L.append("service_area_zips:")
    if zips:
        for z in zips:
            src = next((f.url for f in v.zips if f.value == z), None) or next(
                (o.url for o in v.offices if z in o.zips), ""
            )
            L.append(f'  - "{z}"  # source: {src}')
        if v.places:
            L.append(
                f"  # TODO: the site also names {', '.join(sorted({p.value for p in v.places}))[:100]}. "
                "Add their zip codes if you serve them."
            )
    else:
        places = ", ".join(sorted({p.value for p in v.places}))
        hint = f" The site names: {places[:100]}." if places else ""
        L.append(f"  - TODO  # TODO: no zip codes were found.{hint} List every zip code you serve.")

    if logo:
        L.append(
            f"logo: {logo[0]}  # TODO: guess. Downloaded from {logo[1]}. Confirm it is the right logo."
        )
    else:
        L.append(
            "logo: TODO  # TODO: no logo could be downloaded. Put a logo file in this folder and name it here."
        )
    if brand:
        L.append(
            f'brand_color: "{brand[0]}"  # TODO: guess from the site ({brand[1]}). Confirm the brand color.'
        )
    else:
        L.append(
            'brand_color: TODO  # TODO: hex brand color such as "#F59E0B". None was found on the site.'
        )
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------- routing.yaml
def render_routing(url: str, v: Verified, today: date) -> str:
    L = [header(url, "routing.yaml", today), "offices:"]
    offices = v.offices or []
    used: set[str] = set()
    if not offices:
        L.append(
            "  - id: main\n    name: TODO  # TODO: no offices were found on the website. Name each office.\n"
            "    zips:\n      - TODO  # TODO: zip codes this office serves."
        )
        L.append(_rep_stub())
    for o in offices:
        oid = slugify(o.name)
        while oid in used:
            oid += "_2"
        used.add(oid)
        L.append(f"  - id: {oid}\n    name: {q(o.name)}  # source: {o.url}")
        if o.zips:
            L.append("    zips: [" + ", ".join(f'"{z}"' for z in o.zips) + f"]  # source: {o.url}")
        else:
            L.append(
                "    zips:\n      - TODO  # TODO: the site gives no zip codes for this office. List them."
            )
        L.append(_rep_stub())
    kind = v.appointment_kind or "free consultation"
    L.append(
        "\nassignment: round_robin\n\nhot_lead:\n  notify: immediate\n  slack_mention: true\n  offer_earliest_slot: true\n"
    )
    L.append(
        f"appointment:\n  kind: {q(kind)}  # TODO: guess. What is the first appointment called?\n"
        "  duration_minutes: 60  # TODO: guess. How long does it take?\n"
        "  slots_to_offer: 3\n  lookahead_days: 7\n  minimum_notice_hours: 2"
    )
    L.append('\nslack_channel: "#new-leads"  # TODO: guess. The channel that gets lead pings.')
    return "\n".join(L) + "\n"


def _rep_stub() -> str:
    return (
        "    reps:\n"
        "      - id: TODO  # TODO: reps are never on a public website. Add each real rep, lowercase_with_underscores.\n"
        "        name: TODO\n"
        "        email: TODO\n"
        "        business_hours:\n"
        '          mon: TODO  # TODO: "HH:MM-HH:MM" when this rep can take appointments.'
    )


# --------------------------------------------------------------- qualification.yaml
def _cond(r: Any, types: dict[str, str], options: dict[str, list[str]]) -> str:
    val = rule_value(r, types, options)
    parts = [f"field: {r.field}", f"op: {r.op}"]
    if r.op != "exists":
        parts.append(
            f"value: {json.dumps(_num(val) if isinstance(val, float) else val, ensure_ascii=False)}"
        )
    return "{" + ", ".join(parts) + "}"


def render_qualification(url: str, v: Verified, today: date) -> str:
    L = [header(url, "qualification.yaml", today), "required_fields:"]
    types = {f.key: f.type for f in v.fields}
    options = {f.key: f.options for f in v.fields}
    for f in v.fields:
        L.append(f"  - key: {f.key}\n    type: {f.type}")
        if f.options:
            L.append("    options: [" + ", ".join(q(o) for o in f.options) + "]")
        why = " ".join(f.why.split())[:90]
        L.append(f"    question: {q(f.question)}  # TODO: guess. {why}")

    if v.disqualify:
        L.append("\ndisqualify_if:")
        for r in v.disqualify:
            L.append(f"  - name: {slugify(r.name)}")
            L.append(
                f"    when: [{_cond(r, types, options)}]  # TODO: guess. Confirm this really disqualifies a lead."
            )
            L.append(f"    reason: {q(r.reason)}")
            if r.close_message:
                L.append(f"    close_message: {q(r.close_message)}")
    else:
        L.append(
            "\ndisqualify_if: []  # TODO: no rules were proposed. Add rules for leads you cannot serve."
        )

    L.append("\nscore_weights:")
    total = 0
    if v.score:
        for r in v.score:
            total += r.points or 0
            L.append(f"  - name: {slugify(r.name)}")
            L.append(
                f"    when: [{_cond(r, types, options)}]  # TODO: guess. {' '.join(r.reason.split())[:80]}"
            )
            L.append(f"    points: {r.points}")
    else:
        total = 10
        L.append(
            "  - name: has_email\n    when: [{field: email, op: exists}]  # TODO: placeholder. Replace with real scoring rules.\n    points: 10"
        )
    hot = max(2, round(total * 0.7))
    warm = max(1, min(hot - 1, round(total * 0.4)))
    L.append(
        f"\nhot_lead_threshold: {hot}  # TODO: guess (70% of the {total} points available). Where does a lead become hot?"
    )
    L.append(f"warm_lead_threshold: {warm}  # TODO: guess (40%). Where does a lead become warm?")
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------- crm_mapping.yaml
def render_crm(url: str, v: Verified, today: date) -> str:
    L = [header(url, "crm_mapping.yaml", today)]
    L.append(
        "crm: hubspot  # TODO: guess. HubSpot is the only CRM supported today. Confirm it is yours.\n"
        "pipeline: TODO  # TODO: the name of your sales pipeline.\n"
        "stage_on_create: TODO  # TODO: stage name for a new lead.\n"
        "stage_on_booked: TODO  # TODO: stage name once an appointment is booked.\n"
        "field_map:"
    )
    for f in v.fields:
        L.append(
            f"  {f.key}: {f.key}  # TODO: guess. The CRM property that stores this answer. It must exist."
        )
    for key in CORE_CRM_FIELDS:
        L.append(
            f"  {key}: {DEFAULT_PROPERTY[key]}  # TODO: guess. Confirm this CRM property exists."
        )
    return "\n".join(L) + "\n"


# --------------------------------------------------------------------- knowledge
def render_knowledge(v: Verified, url: str) -> dict[str, str]:
    by_topic: dict[str, list] = {}
    for k in v.knowledge:
        by_topic.setdefault(k.topic, []).append(k)
    files: dict[str, str] = {}
    for topic in dict.fromkeys([*CORE_FILES, *by_topic]):
        items = by_topic.get(topic, [])
        title = TITLES[topic]
        if not items:
            files[f"knowledge/{topic}.md"] = (
                f"<!-- TODO: nothing about this topic was found on the website. Write the real policy, "
                f"or delete this file. Until then the agent will say a rep will confirm. -->\n# {title}\n"
            )
            continue
        body = [
            f"<!-- TODO: drafted from {url}. Check that every statement is accurate and current, "
            "then delete this line. -->",
            f"# {title}\n",
        ]
        for k in items:
            body.append(f"## {k.heading}\n{k.text.strip()}\n<!-- source: {k.url} -->\n")
        files[f"knowledge/{topic}.md"] = "\n".join(body)
    return files
