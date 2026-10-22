import re
from types import SimpleNamespace

import pytest

from leadagent.agent import build_system_prompt
from leadagent.agent.prompt import first_turn_context, local_time_note
from leadagent.llm import AnthropicLLM, ScriptedLLM, reply, text, tool_use
from leadagent.session import LeadSession
from tests.conftest import NIGHT_TIME


def test_prompt_is_built_from_config_with_nothing_left_over(bundle):
    p = build_system_prompt(bundle)
    assert not re.search(r"\{\{\w+\}\}", p)
    assert bundle.company.name in p and bundle.company.reply_signature in p
    for f in bundle.qualification.required_fields:
        assert f.key in p and f.question in p
    for r in bundle.qualification.disqualify_if:
        assert r.name in p
    assert "Mon 08:00-18:00" in p and "21:00 to 08:00" in p and "60 minutes" in p
    assert "free in-home solar consultation" in p


def test_prompt_states_every_guardrail(bundle):
    p = build_system_prompt(bundle).lower()
    for phrase in [
        "never state a price",
        "escalate_to_human",
        "quiet hours",
        "untrusted input",
        "never reveal",
        "never book",
        "<lead_message>",
    ]:
        assert phrase in p


def test_first_turn_context_has_local_time_and_source(bundle, new_lead, clock):
    s = LeadSession(lead=new_lead(source="missed_call", phone="+13035550142", name=None))
    ctx = first_turn_context(s, bundle, clock.now())
    assert "source: missed_call" in ctx and "name: unknown" in ctx
    assert "Tuesday 2026-10-27 10:00 America/Denver (office is open)" in ctx


def test_local_time_note_flags_quiet_hours(bundle):
    note = local_time_note(bundle, NIGHT_TIME)
    assert "office is closed" in note and "quiet hours" in note


# --------------------------------------------------------------- AnthropicLLM wrapper
class FakeBlock:
    def __init__(self, **d):
        self.d = d

    def model_dump(self, exclude_none=False):
        return dict(self.d)


class FakeMessages:
    def __init__(self, sink):
        self.sink = sink

    def create(self, **kwargs):
        self.sink.append(kwargs)
        return SimpleNamespace(
            content=[
                FakeBlock(type="thinking", thinking="", signature="sig"),
                FakeBlock(type="tool_use", id="t1", name="x", input={}),
            ],
            stop_reason="tool_use",
            usage=SimpleNamespace(model_dump=lambda exclude_none=True: {"input_tokens": 5}),
        )


def fake_client():
    sink = []
    client = SimpleNamespace(
        messages=FakeMessages(sink), beta=SimpleNamespace(messages=FakeMessages(sink))
    )
    return client, sink


def test_anthropic_request_shape_has_no_sampling_params_and_caches_system(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    client, sink = fake_client()
    llm = AnthropicLLM(client=client, fallbacks=False)
    resp = llm.create(
        system="SYS", messages=[{"role": "user", "content": "hi"}], tools=[{"name": "t"}]
    )
    [req] = sink
    assert req["model"] == "claude-sonnet-5-5"
    assert req["output_config"] == {"effort": "medium"}
    assert req["system"] == [
        {"type": "text", "text": "SYS", "cache_control": {"type": "ephemeral"}}
    ]
    for banned in ("temperature", "top_p", "top_k", "thinking", "tool_choice", "budget_tokens"):
        assert banned not in req
    # thinking block is preserved verbatim for replay
    assert resp.content[0] == {"type": "thinking", "thinking": "", "signature": "sig"}
    assert resp.stop_reason == "tool_use" and resp.usage == {"input_tokens": 5}


def test_anthropic_model_and_effort_from_env(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-haiku-5-5")
    monkeypatch.setenv("ANTHROPIC_EFFORT", "low")
    client, sink = fake_client()
    AnthropicLLM(client=client, fallbacks=False).create(system="s", messages=[], tools=[])
    assert sink[0]["model"] == "claude-haiku-5-5" and sink[0]["output_config"] == {"effort": "low"}


def test_fallbacks_use_beta_endpoint_by_default(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_FALLBACKS", raising=False)
    client, sink = fake_client()
    AnthropicLLM(client=client).create(system="s", messages=[], tools=[])
    assert (
        sink[0]["betas"] == ["server-side-fallback-2026-07-01"]
        and sink[0]["fallbacks"] == "default"
    )
    monkeypatch.setenv("ANTHROPIC_FALLBACKS", "0")
    client, sink = fake_client()
    AnthropicLLM(client=client).create(system="s", messages=[], tools=[])
    assert "fallbacks" not in sink[0]


def test_scripted_llm_plays_in_order_and_ends_quietly():
    llm = ScriptedLLM([reply(tool_use("check_existing_contact")), RuntimeError("boom")])
    first = llm.create(system="", messages=[], tools=[])
    assert first.stop_reason == "tool_use" and first.content[0]["id"].startswith("toolu_")
    with pytest.raises(RuntimeError):
        llm.create(system="", messages=[], tools=[])
    assert llm.create(system="", messages=[], tools=[]).stop_reason == "end_turn"
    assert llm.calls == 3
    assert reply(text("hi")).stop_reason == "end_turn"
