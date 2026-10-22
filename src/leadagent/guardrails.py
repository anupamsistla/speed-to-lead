"""Deterministic guardrail helpers enforced in code, not just in the prompt."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from leadagent.config.schemas import CompanyConfig


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def in_quiet_hours(company: CompanyConfig, now: datetime) -> bool:
    local = now.astimezone(ZoneInfo(company.timezone))
    cur = local.hour * 60 + local.minute
    start, end = _minutes(company.quiet_hours.start), _minutes(company.quiet_hours.end)
    if start == end:
        return False
    if start < end:
        return start <= cur < end
    return cur >= start or cur < end  # window wraps midnight


def quiet_hours_end(company: CompanyConfig, now: datetime) -> datetime:
    """The next moment outbound messages are allowed again (now, if not in quiet hours)."""
    if not in_quiet_hours(company, now):
        return now
    tz = ZoneInfo(company.timezone)
    local = now.astimezone(tz)
    end = _minutes(company.quiet_hours.end)
    candidate = local.replace(hour=end // 60, minute=end % 60, second=0, microsecond=0)
    if candidate <= local:
        candidate += timedelta(days=1)
    return candidate


# --------------------------------------------------------------------- inbound text
_OPT_OUT_EXACT = {
    "stop",
    "stopall",
    "stop all",
    "unsubscribe",
    "cancel",
    "end",
    "quit",
    "optout",
    "opt out",
}
_OPT_OUT_PHRASE = re.compile(
    r"\b(stop (texting|messaging|contacting|sending|calling|emailing)|"
    r"(don'?t|do not|never) (text|message|contact|call) me|remove me|take me off|"
    r"opt[- ]?out|unsubscribe|leave me alone)\b",
    re.I,
)
_OPT_OUT_PLEASE = re.compile(r"^(please )?stop( it| now)?$", re.I)
_OPT_IN_EXACT = {"start", "unstop", "subscribe"}

_INJECTION = {
    "override_instructions": re.compile(
        r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(instructions?|rules?|prompts?|"
        r"guidelines?|system)\b",
        re.I,
    ),
    "reveal_prompt": re.compile(
        r"\b(reveal|show|print|repeat|output|tell me)\b[^.\n]{0,30}\b(system prompt|your prompt|"
        r"instructions|your rules|initial prompt)\b|\bsystem prompt\b",
        re.I,
    ),
    "role_change": re.compile(
        r"\b(you are now|act as|pretend to be|developer mode|jailbreak|new instructions?)\b", re.I
    ),
    "tool_manipulation": re.compile(
        r"\b(call|run|invoke|execute|use)\b[^.\n]{0,25}\b(tool|function|book_appointment|update_crm|"
        r"notify_rep|escalate_to_human|send_message|score_lead|get_slots)\b|"
        r"\b(book_appointment|update_crm|notify_rep|escalate_to_human|score_lead)\b",
        re.I,
    ),
    "score_manipulation": re.compile(
        r"\b(set|mark|make|change)\b[^.\n]{0,20}\b(score|tier|hot lead|qualified)\b", re.I
    ),
    "markup_escape": re.compile(r"</?\s*(lead_message|system_note|lead_context|system)\b", re.I),
}

_PERSON = r"(person|human|someone|somebody|rep|representative|agent|manager|supervisor|salesperson)"
_HUMAN_REQUEST = re.compile(
    # a request cue, then "talk/speak/chat/connect ... <a person>". Asking *whether* the sender
    # is a person ("am I talking to a real person?") has no cue and does not match.
    rf"\b(want|need|prefer|wanna|rather|like|demand|please|can i|could i|may i|let me|let's)\b"
    rf"[^.?!]{{0,25}}\b(talk|speak|chat|connect)\w*\b[^.?!]{{0,15}}\b{_PERSON}\b|"
    rf"^\W*(speak|talk|chat) (to|with) (a |an |the )?(real |actual |live )?{_PERSON}\b|"
    r"\b(want|need|prefer|wanna|rather|demand)\b[^.?!]{0,10}\b(a |an |the )?(real|actual|live) "
    r"(person|human)\b|"
    rf"\b(get|give|put|connect|transfer) me (to |with |through to )?(a |an |the )?"
    rf"(real |actual |live )?{_PERSON}\b|"
    r"\b(can|could|have|get) (someone|somebody|a rep|a person|a human) "
    r"(call|phone|contact|reach)\b|"
    r"\b(call|phone) me\b|\bcustomer service\b",
    re.I,
)
_ANGER = re.compile(
    r"\b(furious|outraged|livid|pissed|ridiculous|unacceptable|terrible|worst|scam(mers?)?|"
    r"rip[- ]?off|lawsuit|lawyer|attorney|sue you|report you|harass(ing|ment)?|fed up|"
    r"sick of|useless|incompetent|garbage|disgusting|idiots?|stupid|hate (you|this)|"
    r"fuck\w*|shit\w*|bullshit|asshole|damn it|waste of (my )?time)\b",
    re.I,
)


def _norm(text: str) -> str:
    return re.sub(r"[^a-z ]", "", text.lower()).strip()


def detect_opt_out(text: str) -> bool:
    t = text.strip()
    return bool(
        _norm(t) in _OPT_OUT_EXACT or _OPT_OUT_PLEASE.match(_norm(t)) or _OPT_OUT_PHRASE.search(t)
    )


def detect_opt_in(text: str) -> bool:
    return _norm(text) in _OPT_IN_EXACT


def detect_injection(text: str) -> list[str]:
    return [name for name, rx in _INJECTION.items() if rx.search(text)]


def detect_human_request(text: str) -> bool:
    return bool(_HUMAN_REQUEST.search(text))


def detect_anger(text: str) -> bool:
    if _ANGER.search(text):
        return True
    letters = [c for c in text if c.isalpha()]
    shouting = len(letters) >= 12 and sum(c.isupper() for c in letters) / len(letters) > 0.8
    return shouting and text.count("!") >= 2


def escape_lead_text(text: str) -> str:
    """Neutralize markup so lead text cannot close or forge the tags the prompt relies on."""
    return text.replace("<", "&lt;").replace(">", "&gt;")


# -------------------------------------------------------------------- outbound claims
_MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s?([kK])?")
_PERCENT = re.compile(r"(\d+(?:\.\d+)?)\s?%")
_DURATION = re.compile(r"\b(\d+(?:\.\d+)?)[- ]?(year|yr|month)s?\b", re.I)
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
_RISKY_PHRASE = re.compile(
    r"\b(zero down|no money down|interest[- ]free|risk[- ]free|apr|interest rate|"
    r"monthly payment|lock(?:ed)? in (?:your |the )?rate|guarantee[sd]?|guaranteed|"
    r"promise[sd]?)\b",
    re.I,
)
_NEGATION_BEFORE = re.compile(r"(?:\b(?:not|no|never|without|cannot)|n't)\W+(?:\w+\W+){0,2}$", re.I)


def _num(raw: str, k: str | None = None) -> float:
    value = float(raw.replace(",", ""))
    return value * 1000 if k else value


def _is_negated(text: str, start: int) -> bool:
    return bool(_NEGATION_BEFORE.search(text[max(0, start - 30) : start]))


def _affirmative(phrase: str, knowledge: str) -> bool:
    return any(
        not _is_negated(knowledge, m.start())
        for m in re.finditer(re.escape(phrase), knowledge, re.I)
    )


def find_unsupported_claims(body: str, knowledge: str, lead_text: str = "") -> list[str]:
    """Prices, rates, durations and guarantees in an outbound message that neither the
    knowledge base nor the lead's own words support. Empty list means the message is clean."""
    problems: list[str] = []
    known_money = {_num(m.group(1), m.group(2)) for m in _MONEY.finditer(knowledge)}
    known_percent = {float(m.group(1)) for m in _PERCENT.finditer(knowledge)}
    known_durations = {
        (float(m.group(1)), m.group(2).lower()[:2]) for m in _DURATION.finditer(knowledge)
    }
    lead_numbers = {_num(n) for n in _NUMBER.findall(lead_text)}

    for m in _MONEY.finditer(body):
        v = _num(m.group(1), m.group(2))
        if v not in known_money and v not in lead_numbers:
            problems.append(f"price {m.group(0).strip()} is not in the knowledge base")
    for m in _PERCENT.finditer(body):
        v = float(m.group(1))
        if v not in known_percent and v not in lead_numbers:
            problems.append(f"rate {m.group(0).strip()} is not in the knowledge base")
    for m in _DURATION.finditer(body):
        key = (float(m.group(1)), m.group(2).lower()[:2])
        if key not in known_durations and key[0] not in lead_numbers:
            problems.append(f"term '{m.group(0)}' is not in the knowledge base")
    for m in _RISKY_PHRASE.finditer(body):
        phrase = m.group(0).lower()
        if _is_negated(body, m.start()):
            continue
        if phrase in {"guarantee", "guarantees", "guaranteed", "promise", "promised", "promises"}:
            stem = "guarantee" if phrase.startswith("guarantee") else "promise"
            if _affirmative(stem, knowledge):
                continue
        elif phrase in knowledge.lower():
            continue
        problems.append(
            f"'{m.group(0)}' is a financing term or guarantee not in the knowledge base"
        )
    return problems
