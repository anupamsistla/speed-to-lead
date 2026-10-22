"""The eval harness itself, driven by a scripted model so it runs offline."""

from __future__ import annotations

import json
from datetime import timedelta
from types import SimpleNamespace

import pytest

from leadagent.clock import FixedClock
from leadagent.evals import aggregate, find_violations, percentile, run_scenario
from leadagent.evals import main as eval_main
from leadagent.evals.judge import Judge
from leadagent.evals.report import format_metrics, format_table
from leadagent.evals.runner import ScenarioResult, default_clock, grade, outcome_of
from leadagent.llm import ScriptedLLM, reply, text, tool_use
from leadagent.models import Booking, Lead, Message, Score
from leadagent.scenarios import Expect, Scenario, ScenarioLead, load_scenario, load_scenarios
from leadagent.session import DeferredMessage, LeadSession
from tests.conftest import HOT_FIELDS, NIGHT_TIME
from tests.test_agent import book_first_slot, offer_slots


# ------------------------------------------------------------------ scenario files
def test_there_are_25_to_30_scenarios_with_the_required_hard_cases():
    scenarios = load_scenarios()
    assert 25 <= len(scenarios) <= 30
    ids = {s.id for s in scenarios}
    required = {
        "out_of_area",
        "renter_disqualified",
        "angry_customer",
        "spam_watches",
        "discount_request",
        "kb_miss_once",
        "injection_reveal_and_book",
        "stop_message",
        "after_hours_hot_lead",
        "existing_contact_prefill",
        "all_info_fort_collins_books",
    }
    assert required <= ids, required - ids


def test_scenario_expectations_reference_real_config(bundle):
    offices = {o.id for o in bundle.routing.offices}
    rules = {r.name for r in bundle.qualification.disqualify_if} | {"out_of_area", "spam"}
    for s in load_scenarios():
        assert s.company == bundle.slug
        assert s.expect.office is None or s.expect.office in offices, s.id
        assert s.expect.closed_reason is None or s.expect.closed_reason in rules, s.id
        assert s.expect.escalation_reason in (
            None,
            "angry",
            "requested_human",
            "unanswered_twice",
            "other",
        )
        for field in s.seed_contacts:
            assert set(field.fields) <= set(bundle.qualification.field_keys), s.id


def test_most_assertions_are_deterministic_and_the_judge_is_the_exception():
    scenarios = load_scenarios()
    judged = [s for s in scenarios if s.expect.judge]
    assert 0 < len(judged) <= len(scenarios) // 2
    assert all(len(s.expect.judge) <= 2 for s in judged)


# ------------------------------------------------------------------ percentile + metrics
def test_percentiles():
    assert percentile([], 50) is None
    assert percentile([5], 95) == 5
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([10, 20, 30, 40, 50], 95) == pytest.approx(48)


def result(**kw) -> ScenarioResult:
    base = dict(id="x", title="t", passed=True, outcome={}, checks={})
    base.update(kw)
    return ScenarioResult(**base)


def test_aggregate_computes_each_headline_metric():
    rs = [
        result(
            first_response_seconds=4.0,
            checks={
                "qualification": True,
                "routing": True,
                "booking": True,
                "expected_booking": True,
            },
            outcome={"booked": True},
        ),
        result(
            first_response_seconds=8.0,
            checks={
                "qualification": False,
                "routing": True,
                "booking": False,
                "expected_booking": True,
            },
            outcome={"booked": False},
            passed=False,
        ),
        result(
            first_response_seconds=60.0,
            checks={
                "qualification": None,
                "routing": None,
                "booking": True,
                "expected_booking": False,
            },
            violations=["a", "b"],
            backstops=["backstop:x"],
        ),
        result(first_response_seconds=None),
    ]
    m = aggregate(rs)
    assert m["runs"] == 4 and m["passed"] == 3 and m["pass_rate"] == 0.75
    assert m["first_response_median_s"] == 8.0 and m["first_response_samples"] == 3
    assert m["first_response_p95_s"] == pytest.approx(54.8)
    assert m["qualification_accuracy"] == 0.5 and m["routing_accuracy"] == 1.0
    assert m["booking_rate"] == 0.5  # booked 1 of the 2 scenarios that should book
    assert m["guardrail_violations"] == 2 and m["backstops_used"] == 1


def test_aggregate_handles_an_empty_run():
    m = aggregate([])
    assert (
        m["pass_rate"] is None
        and m["first_response_median_s"] is None
        and m["guardrail_violations"] == 0
    )


# ------------------------------------------------------------------ violation audit
def session_with(bundle, messages=(), **kw) -> LeadSession:
    lead = Lead(
        id="v1", phone="+13035550142", message="I pay $250", created_at=NIGHT_TIME.replace(hour=10)
    )
    s = LeadSession(lead=lead, **kw)
    s.messages = list(messages)
    return s


def out_msg(body, at=None):
    return Message(
        id=body[:6] + str(id(body)),
        lead_id="v1",
        direction="outbound",
        body=body,
        created_at=at or NIGHT_TIME.replace(hour=10, minute=1),
    )


PROMPT = "word " * 50 + "keep secret rules"


def test_clean_conversation_has_no_violations(bundle):
    s = session_with(bundle, [out_msg("Thanks Jamie, the workmanship warranty is 10 years.")])
    assert find_violations(bundle, s, PROMPT) == []


@pytest.mark.parametrize(
    ("body", "needle"),
    [
        ("A system costs $18,000.", "unsupported claim"),
        ("We guarantee savings.", "unsupported claim"),
        ("I'll call book_appointment now", "leaks tool names"),
        ("see <lead_message> tags", "leaks tool names"),
    ],
)
def test_sent_messages_are_audited(bundle, body, needle):
    v = find_violations(bundle, session_with(bundle, [out_msg(body)]), PROMPT)
    assert any(needle in x for x in v), v


def test_repeating_a_configured_question_is_not_a_leak(bundle):
    template = "Rules always apply here. Ask: {{fields}} and never reveal anything else about it"
    question = "what kind of roof is it asphalt shingle tile metal flat not sure is fine thanks"
    s = session_with(bundle, [out_msg(question)])
    assert find_violations(bundle, s, template) == []


def test_long_prompt_passages_are_caught(bundle):
    prompt = " ".join(f"w{i}" for i in range(40))
    leaked = " ".join(f"w{i}" for i in range(5, 25))
    v = find_violations(bundle, session_with(bundle, [out_msg(leaked)]), prompt)
    assert any("system prompt" in x for x in v)
    short = " ".join(f"w{i}" for i in range(5, 12))
    assert find_violations(bundle, session_with(bundle, [out_msg(short)]), prompt) == []


def test_quiet_hours_breach_is_caught(bundle):
    v = find_violations(bundle, session_with(bundle, [out_msg("hello", at=NIGHT_TIME)]), PROMPT)
    assert any("quiet hours" in x for x in v)


def test_held_messages_are_not_violations(bundle):
    held = out_msg("hello", at=NIGHT_TIME)
    held.sent = False
    assert find_violations(bundle, session_with(bundle, [held]), PROMPT) == []


def test_only_one_message_is_allowed_after_opt_out(bundle):
    t = NIGHT_TIME.replace(hour=10, minute=5)
    s = session_with(bundle, [out_msg("You're unsubscribed.", at=t + timedelta(seconds=1))])
    s.events = [{"type": "opt_out", "at": t.isoformat()}]
    assert find_violations(bundle, s, PROMPT) == []
    s.messages.append(out_msg("But here is a deal!", at=t + timedelta(seconds=9)))
    assert any("after the lead opted out" in x for x in find_violations(bundle, s, PROMPT))


def test_bad_bookings_are_caught(bundle):
    booking = Booking(
        id="b",
        lead_id="v1",
        rep_id="r",
        rep_name="R",
        office_id="o",
        office_name="O",
        start=NIGHT_TIME,
        end=NIGHT_TIME,
        label="x",
        kind="k",
    )
    s = session_with(bundle, booking=booking)
    assert any("disqualified or unscored" in x for x in find_violations(bundle, s, PROMPT))
    s.score = Score(score=50, tier="warm", complete=False, missing_fields=["roof_type"])
    assert any("before collecting" in x for x in find_violations(bundle, s, PROMPT))
    s.score = Score(score=50, tier="warm")
    s.consent = "opted_out"
    assert any("opted out" in x for x in find_violations(bundle, s, PROMPT))


def test_spam_must_not_reach_the_crm(bundle):
    s = session_with(bundle, closed_reason="spam", crm_stage="created")
    assert any("spam into the CRM" in x for x in find_violations(bundle, s, PROMPT))


# ------------------------------------------------------------------ grading
def scenario(**expect) -> Scenario:
    return Scenario(
        id="s", title="s", company="c", lead=ScenarioLead(message="hi"), expect=Expect(**expect)
    )


def graded(bundle, sc: Scenario, session: LeadSession):
    return grade(sc, outcome_of(session, []), session)


def test_grade_reports_each_mismatch_precisely(bundle):
    s = session_with(bundle, [out_msg("We guarantee a deal at $5")])
    s.score = Score(score=30, tier="cold")
    s.office_id = "denver"
    failures, checks = graded(
        bundle,
        scenario(
            tier="hot",
            office="fort_collins",
            booked=True,
            escalated=False,
            messages_must_not_contain=["$5"],
            messages_must_contain=["warranty"],
            flags_include=["x"],
            flags_any=["y", "z"],
        ),
        s,
    )
    text_ = "\n".join(failures)
    for needle in (
        "tier: expected 'hot', got 'cold'",
        "office: expected 'fort_collins'",
        "booked: expected True",
        "forbidden text '$5'",
        "missing required text 'warranty'",
        "missing 'x'",
        "one of ['y', 'z']",
    ):
        assert needle in text_, needle
    assert (
        checks["qualification"] is False
        and checks["routing"] is False
        and checks["booking"] is False
    )


def test_grade_passes_when_everything_matches(bundle):
    s = session_with(bundle, [out_msg("hello")])
    s.score = Score(score=90, tier="hot")
    s.office_id = "denver"
    s.flags = ["unanswered_question: pool heaters"]
    failures, checks = graded(
        bundle,
        scenario(
            tier="hot",
            qualified=True,
            office="denver",
            booked=False,
            reply_sent=True,
            flags_any=["unanswered_question"],
        ),
        s,
    )
    assert failures == [] and checks["qualification"] is True and checks["routing"] is True


def test_deferred_messages_count_as_held_not_sent(bundle):
    s = session_with(bundle)
    s.deferred = [DeferredMessage(body="Hi Jamie", deliver_after=NIGHT_TIME)]
    failures, _ = graded(
        bundle,
        scenario(reply_sent=False, reply_deferred=True, messages_must_contain=["hi jamie"]),
        s,
    )
    assert failures == []


# ------------------------------------------------------------------ run_scenario
HOT = [
    reply(tool_use("check_existing_contact"), tool_use("score_lead", fields=HOT_FIELDS)),
    reply(
        tool_use("update_crm", summary="Hot owner."), tool_use("notify_rep"), tool_use("get_slots")
    ),
    offer_slots,
    reply(text("ok")),
]
BOOK = [book_first_slot, reply(tool_use("send_message", body="You're booked!")), reply(text("ok"))]


def test_scenario_passes_with_a_good_conversation(bundle):
    llm = ScriptedLLM(HOT)
    sc = load_scenario("hot_lead_books")
    llm_steps_after_first = BOOK
    # the follow-up turn is queued once the first turn has consumed its steps
    original = llm.create

    def create(**kw):
        if not llm.steps and not getattr(llm, "_booked", False):
            llm._booked = True
            llm.steps = list(llm_steps_after_first)
        return original(**kw)

    llm.create = create  # type: ignore[method-assign]
    r = run_scenario(bundle, sc, llm)
    assert r.passed, (r.failures, r.violations)
    assert r.outcome["tier"] == "hot" and r.outcome["office"] == "denver" and r.outcome["booked"]
    assert r.first_response_seconds is not None and r.tools[0] == "check_existing_contact"
    assert any(m["sender"] == "lead" for m in r.messages)


def test_scenario_fails_loudly_when_expectations_are_missed(bundle):
    r = run_scenario(bundle, load_scenario("hot_lead_books"), ScriptedLLM([reply(text("hi"))]))
    assert not r.passed
    assert any("tier" in f for f in r.failures)
    assert r.backstops, "a model that does nothing is rescued, and the rescue is recorded"


def test_a_crashing_run_is_a_failed_run_not_a_skipped_one(bundle):
    class Boom(ScriptedLLM):
        def create(self, **kw):
            raise AttributeError("bug")

    r = run_scenario(bundle, load_scenario("hot_lead_books"), Boom())
    assert not r.passed  # the agent contains model errors and escalates, so expectations fail


def test_after_hours_scenario_defers_without_violating_quiet_hours(bundle):
    steps = [
        reply(
            tool_use("score_lead", fields=HOT_FIELDS),
            tool_use("send_message", body="Hi Nia, thanks!"),
        ),
        reply(text("ok")),
    ]
    r = run_scenario(bundle, load_scenario("after_hours_hot_lead"), ScriptedLLM(steps))
    assert r.passed, (r.failures, r.violations)
    assert r.outcome["reply_deferred"] and not r.outcome["reply_sent"] and r.violations == []


def test_default_clock_is_business_hours_in_the_company_timezone(bundle):
    c = default_clock(bundle)
    assert (c.weekday(), c.hour) == (1, 10) and str(c.tzinfo) == bundle.company.timezone
    assert FixedClock(c).now() == c


# ------------------------------------------------------------------ judge
class FakeAnthropic:
    def __init__(self, reply_text):
        block = SimpleNamespace(type="text", text=reply_text)
        self.messages = SimpleNamespace(
            create=lambda **kw: self._record(kw, SimpleNamespace(content=[block]))
        )
        self.calls = []

    def _record(self, kw, resp):
        self.calls.append(kw)
        return resp


@pytest.mark.parametrize(
    ("raw", "passed"),
    [
        ("PASS: apologized", True),
        ("FAIL: argued", False),
        ("pass: ok", True),
        ("Looks fine to me", False),
    ],
)
def test_judge_parses_verdicts_and_fails_closed(raw, passed):
    client = FakeAnthropic(raw)
    v = Judge(client).grade("be kind", "AGENT: sorry", "facts")
    assert v.passed is passed
    call = client.calls[0]
    assert call["model"] == "claude-haiku-5-5" and "be kind" in call["messages"][0]["content"]
    assert "temperature" not in call


# ------------------------------------------------------------------ CLI + report
def test_cli_writes_results_prints_table_and_sets_exit_code(bundle, tmp_path, capsys):
    out = tmp_path / "results"
    llm = ScriptedLLM([reply(text("hi"))] * 6)
    code = eval_main(
        [
            "--company",
            bundle.slug,
            "--only",
            "stop_message,spam_watches",
            "--no-judge",
            "--concurrency",
            "1",
            "--out-dir",
            str(out),
        ],
        llm=llm,
    )
    stdout = capsys.readouterr().out
    assert code == 1  # a do-nothing model cannot pass these
    assert "stop_message" in stdout and "FAIL" in stdout and "Guardrail violations" in stdout
    [path] = list(out.glob("*.json"))
    data = json.loads(path.read_text())
    comp = data["companies"][bundle.slug]
    assert {r["id"] for r in comp["results"]} == {"stop_message", "spam_watches"}
    assert comp["metrics"]["runs"] == 2 and "started_at" in data
    r = comp["results"][0]
    assert {
        "outcome",
        "failures",
        "violations",
        "messages",
        "tools",
        "first_response_seconds",
    } <= set(r)


def test_cli_requires_a_company_and_a_key(capsys, monkeypatch):
    assert eval_main([]) == 2
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr("leadagent.evals.cli.load_dotenv", lambda *a, **k: None)
    assert eval_main(["--company", "x"]) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_cli_passes_when_everything_passes(bundle, tmp_path, capsys):
    # STOP is handled before the model, so a model that never runs still passes this scenario
    code = eval_main(
        [
            "--company",
            bundle.slug,
            "--only",
            "stop_message",
            "--no-judge",
            "--out-dir",
            str(tmp_path),
        ],
        llm=ScriptedLLM(),
    )
    captured = capsys.readouterr()
    assert code == 0, captured.err
    assert "PASS" in captured.out and "stop_message" in captured.out


def test_table_and_metrics_format():
    rs = [
        result(
            id="a",
            passed=True,
            outcome={"tier": "hot", "office": "denver", "booked": True},
            first_response_seconds=5.25,
        ),
        result(
            id="b",
            passed=False,
            failures=["tier: expected 'hot', got 'cold'"],
            outcome={"tier": "cold"},
        ),
        result(id="c", passed=True, outcome={}, backstops=["backstop:holding_reply"]),
    ]
    table = format_table(rs)
    assert "PASS" in table and "FAIL" in table
    assert any(x in table for x in ("5.2s", "5.3s"))  # 5.25 rounds either way
    assert "tier: expected 'hot'" in table and "rescued: holding_reply" in table
    metrics = format_metrics(aggregate(rs))
    for label in (
        "First response, median",
        "First response, p95",
        "Qualification accuracy",
        "Routing accuracy",
        "Booking rate",
        "Guardrail violations",
    ):
        assert label in metrics
