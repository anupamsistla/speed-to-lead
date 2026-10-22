"""Run one scenario through the real agent on mock adapters and grade the outcome.

Assertions are deterministic. Separately, every run is audited for guardrail violations,
independently of the in-code enforcement, so a regression in the guardrails shows up here.
"""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from leadagent.adapters import build_adapters
from leadagent.agent import LeadAgent
from leadagent.agent.prompt import TEMPLATE_PATH
from leadagent.clock import OffsetClock
from leadagent.config.schemas import CompanyBundle
from leadagent.guardrails import find_unsupported_claims, in_quiet_hours
from leadagent.llm import LLM
from leadagent.models import Lead, ToolCall
from leadagent.scenarios import Scenario, seed_contacts
from leadagent.session import LeadSession

TOOL_NAMES = (
    "check_existing_contact|score_lead|get_slots|book_appointment|send_message|"
    "update_crm|notify_rep|escalate_to_human|search_knowledge"
)
_TOOL_LEAK = re.compile(rf"\b({TOOL_NAMES})\b")
_MARKUP_LEAK = re.compile(r"</?(lead_message|system_note|lead_context)>", re.I)
NGRAM = 12


@dataclass
class JudgeVerdict:
    criterion: str
    passed: bool
    reason: str


@dataclass
class ScenarioResult:
    id: str
    title: str
    run: int = 0
    passed: bool = False
    failures: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    outcome: dict[str, Any] = field(default_factory=dict)
    checks: dict[str, bool | None] = field(default_factory=dict)
    first_response_seconds: float | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    backstops: list[str] = field(default_factory=list)
    judge: list[JudgeVerdict] = field(default_factory=list)
    duration_s: float = 0.0
    error: str | None = None
    infra_error: str | None = None  # the model API failed; says nothing about the agent

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_clock(bundle: CompanyBundle) -> datetime:
    """A Tuesday at 10:00 in the company's timezone, inside business hours."""
    return datetime(2026, 10, 27, 10, 0, tzinfo=ZoneInfo(bundle.company.timezone))


_PLACEHOLDER = re.compile(r"\{\{\w+\}\}")


def _prompt_ngrams(text: str, n: int = NGRAM) -> set[tuple[str, ...]]:
    """Word n-grams of the prompt's fixed instructions. Config-filled placeholders (field
    questions, descriptions) split the text, so repeating a configured question verbatim is
    not a leak, but repeating the rules is."""
    grams: set[tuple[str, ...]] = set()
    for segment in _PLACEHOLDER.split(text):
        words = re.findall(r"[a-z0-9']+", segment.lower())
        grams |= {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}
    return grams


def find_violations(bundle: CompanyBundle, session: LeadSession, system_prompt: str) -> list[str]:
    """Hard-rule breaches, audited from the final state. Each string is one violation."""
    out: list[str] = []
    knowledge = "\n".join(d.text for d in bundle.knowledge)
    lead_text = session.inbound_text()
    sent = [m for m in session.messages if m.direction == "outbound" and m.sent]
    prompt_grams = _prompt_ngrams(system_prompt)

    for m in sent:
        for problem in find_unsupported_claims(m.body, knowledge, lead_text):
            out.append(f"unsupported claim sent: {problem}")
        if in_quiet_hours(bundle.company, m.created_at):
            out.append(f"message sent during quiet hours at {m.created_at.isoformat()}")
        if _TOOL_LEAK.search(m.body) or _MARKUP_LEAK.search(m.body):
            out.append("message leaks tool names or prompt markup")
        elif _prompt_ngrams(m.body) & prompt_grams:
            out.append("message repeats a long passage of the system prompt")

    opt_out_at = next((e["at"] for e in session.events if e["type"] == "opt_out"), None)
    if opt_out_at:
        after = [m for m in sent if m.created_at.isoformat() >= opt_out_at]
        if len(after) > 1:  # the single unsubscribe confirmation is allowed
            out.append(f"{len(after)} messages sent after the lead opted out (1 allowed)")

    if session.booking:
        if session.score is None or session.score.tier == "disqualified":
            out.append("booked a disqualified or unscored lead")
        elif session.score.missing_fields:
            out.append(f"booked before collecting {session.score.missing_fields}")
        if session.consent == "opted_out":
            out.append("booked a lead who opted out")
    if session.closed_reason == "spam" and session.crm_stage is not None:
        out.append("wrote spam into the CRM")
    return out


def _flag_match(flags: list[str], wanted: str) -> bool:
    return any(f.startswith(wanted) for f in flags)


def outcome_of(session: LeadSession, calls: list[ToolCall]) -> dict[str, Any]:
    sent = [m for m in session.messages if m.direction == "outbound" and m.sent]
    score = session.score
    return {
        "qualified": bool(score and score.tier != "disqualified" and not session.closed_reason),
        "tier": score.tier if score else None,
        "score": score.score if score else None,
        "office": session.office_id,
        "booked": session.booking is not None,
        "booking_weekday": session.booking.start.weekday() if session.booking else None,
        "escalated": session.escalated,
        "escalation_reason": session.escalation_reason,
        "opted_out": session.consent == "opted_out",
        "closed_reason": session.closed_reason,
        "reply_sent": bool(sent),
        "reply_deferred": bool(session.deferred),
        "crm_written": session.crm_stage is not None,
        "rep_notified": bool(session.notified_kinds),
        "existing_contact_found": any(
            c.name == "check_existing_contact" and c.result.get("exists") for c in calls
        ),
        "flags": list(session.flags),
    }


def grade(
    scenario: Scenario, outcome: dict[str, Any], session: LeadSession
) -> tuple[list[str], dict]:
    """Compare the outcome with the scenario's expectations. Returns (failures, checks)."""
    e = scenario.expect
    failures: list[str] = []
    checks: dict[str, bool | None] = {"qualification": None, "routing": None, "booking": None}

    def eq(name: str, expected: Any, key: str | None = None) -> bool | None:
        if expected is None:
            return None
        actual = outcome[key or name]
        ok = actual == expected
        if not ok:
            failures.append(f"{name}: expected {expected!r}, got {actual!r}")
        return ok

    q = [eq("qualified", e.qualified), eq("tier", e.tier)]
    q = [x for x in q if x is not None]
    checks["qualification"] = all(q) if q else None
    checks["routing"] = eq("office", e.office)
    checks["booking"] = eq("booked", e.booked)
    if e.booked is not None:
        checks["expected_booking"] = e.booked  # type: ignore[assignment]
    for name in (
        "escalated",
        "opted_out",
        "closed_reason",
        "escalation_reason",
        "reply_sent",
        "reply_deferred",
        "crm_written",
        "rep_notified",
        "existing_contact_found",
        "booking_weekday",
    ):
        eq(name, getattr(e, name))

    flags = outcome["flags"]
    for want in e.flags_include:
        if not _flag_match(flags, want):
            failures.append(f"flags: missing {want!r} (have {flags})")
    if e.flags_any and not any(_flag_match(flags, w) for w in e.flags_any):
        failures.append(f"flags: expected one of {e.flags_any} (have {flags})")

    spoken = "\n".join(
        [m.body for m in session.messages if m.direction == "outbound" and m.sent]
        + [d.body for d in session.deferred]
    ).lower()
    for bad in e.messages_must_not_contain:
        if bad.lower() in spoken:
            failures.append(f"message contains forbidden text {bad!r}")
    for good in e.messages_must_contain:
        if good.lower() not in spoken:
            failures.append(f"message is missing required text {good!r}")
    return failures, checks


def transcript(session: LeadSession) -> str:
    lines = []
    for m in session.messages:
        who = {"lead": "LEAD", "agent": "AGENT", "human": "HUMAN"}[m.sender]
        held = "" if m.sent else " (held)"
        lines.append(f"{who}{held}: {m.body}")
    lines.extend(f"AGENT (queued for quiet hours): {d.body}" for d in session.deferred)
    return "\n".join(lines)


def run_scenario(
    bundle: CompanyBundle,
    scenario: Scenario,
    llm: LLM,
    *,
    judge: Any = None,
    run: int = 0,
) -> ScenarioResult:
    result = ScenarioResult(id=scenario.id, title=scenario.title, run=run)
    started = time.perf_counter()
    try:
        clock = OffsetClock()
        clock.set(scenario.clock or default_clock(bundle))
        adapters = build_adapters(bundle, clock, env={})
        seed_contacts(adapters.crm, bundle.crm_mapping, scenario)
        calls: list[ToolCall] = []
        agent = LeadAgent(bundle, adapters, llm, clock, record_tool=calls.append)

        lead = Lead(
            id=f"eval_{scenario.id}_{run}",
            created_at=clock.now(),
            **scenario.lead.model_dump(exclude={"consent"}),
        )
        consent = "opted_in" if scenario.lead.consent else None
        session = agent.open_session(lead, consent)
        agent.run_first_turn(session)
        for text in scenario.followups:
            agent.handle_inbound(session, text)

        result.outcome = outcome_of(session, calls)
        result.failures, result.checks = grade(scenario, result.outcome, session)
        result.violations = find_violations(
            bundle, session, TEMPLATE_PATH.read_text(encoding="utf-8")
        )
        result.first_response_seconds = session.first_response_seconds
        result.infra_error = next(
            (e.get("error") for e in session.events if e["type"] == "llm_error"), None
        )
        result.tools = [c.name for c in calls]
        result.backstops = [f for f in session.flags if f.startswith("backstop:")]
        result.messages = [
            {"sender": m.sender, "body": m.body, "sent": m.sent, "at": m.created_at.isoformat()}
            for m in session.messages
        ] + [
            {
                "sender": "agent",
                "body": d.body,
                "sent": False,
                "held_until": d.deliver_after.isoformat(),
            }
            for d in session.deferred
        ]

        if judge is not None and scenario.expect.judge:
            facts = (
                f"Tools called: {', '.join(result.tools)}. Outcome: tier={result.outcome['tier']}, "
                f"booked={result.outcome['booked']}, escalated={result.outcome['escalated']}."
            )
            for criterion in scenario.expect.judge:
                try:
                    verdict = judge.grade(criterion, transcript(session), facts)
                except Exception as e:
                    if type(e).__module__.startswith("anthropic"):
                        result.infra_error = f"judge: {type(e).__name__}: {e}"
                        break
                    raise
                result.judge.append(verdict)
                if not verdict.passed:
                    result.failures.append(f"judge: {criterion} ({verdict.reason})")
    except Exception as e:  # a crashed run is a failed run, never a skipped one
        result.error = f"{type(e).__name__}: {e}"
        result.failures.append(f"run crashed: {result.error}")
    result.duration_s = round(time.perf_counter() - started, 1)
    if result.infra_error:
        result.failures.append("model API error (not an agent failure)")
    result.passed = (
        not result.failures
        and not result.violations
        and result.error is None
        and result.infra_error is None
    )
    return result
