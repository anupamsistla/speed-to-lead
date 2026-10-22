"""LLM access behind a small interface so the agent loop is testable without a network.

AnthropicLLM talks to the Claude API. ScriptedLLM replays canned responses and is the test
double used by the unit tests and API tests.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from typing import Any, Protocol

from pydantic import BaseModel, Field

DEFAULT_MODEL = "claude-sonnet-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMResponse(BaseModel):
    """Content blocks as plain dicts, ready to append to the conversation unchanged."""

    content: list[dict[str, Any]]
    stop_reason: str
    usage: dict[str, Any] = Field(default_factory=dict)


class LLM(Protocol):
    def create(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse: ...


class AnthropicLLM:
    """Claude via the Anthropic SDK.

    - Model comes from ANTHROPIC_MODEL (default claude-sonnet-5-5).
    - No sampling parameters are sent (not accepted by this model family). Depth is controlled
      with output_config.effort (ANTHROPIC_EFFORT, default medium: a good fit for multi-step
      tool use where reply latency matters).
    - Thinking blocks come back inside content and are replayed unchanged by the agent loop.
    - ANTHROPIC_FALLBACKS (default on) re-runs a safety-declined request on the fallback
      model server side. Set it to 0 to turn it off.
    """

    def __init__(
        self,
        *,
        model: str | None = None,
        effort: str | None = None,
        max_tokens: int = 2048,
        fallbacks: bool | None = None,
        client: Any = None,
    ):
        self.model = model or os.environ.get("ANTHROPIC_MODEL") or DEFAULT_MODEL
        self.effort = effort or os.environ.get("ANTHROPIC_EFFORT") or "medium"
        self.max_tokens = max_tokens
        if fallbacks is None:
            fallbacks = os.environ.get("ANTHROPIC_FALLBACKS", "1").strip() not in ("0", "false", "")
        self.fallbacks = fallbacks
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client = client

    def create(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "tools": tools,
            "messages": messages,
            "output_config": {"effort": self.effort},
        }
        if self.fallbacks:
            resp = self.client.beta.messages.create(
                betas=[FALLBACK_BETA], fallbacks="default", **kwargs
            )
        else:
            resp = self.client.messages.create(**kwargs)
        usage = resp.usage.model_dump(exclude_none=True) if resp.usage else {}
        return LLMResponse(
            content=[b.model_dump(exclude_none=True) for b in resp.content],
            stop_reason=resp.stop_reason or "end_turn",
            usage=usage,
        )


# ------------------------------------------------------------------ test double
def text(body: str) -> dict[str, Any]:
    return {"type": "text", "text": body}


def tool_use(name: str, **input_: Any) -> dict[str, Any]:
    return {
        "type": "tool_use",
        "id": f"toolu_{uuid.uuid4().hex[:12]}",
        "name": name,
        "input": input_,
    }


def reply(*blocks: dict[str, Any], stop_reason: str | None = None) -> LLMResponse:
    """A scripted assistant turn. stop_reason defaults to tool_use if any tool block exists."""
    if stop_reason is None:
        stop_reason = "tool_use" if any(b["type"] == "tool_use" for b in blocks) else "end_turn"
    return LLMResponse(content=list(blocks), stop_reason=stop_reason)


Step = LLMResponse | Callable[[list[dict[str, Any]]], LLMResponse] | Exception


class ScriptedLLM:
    """Plays back steps in order. A step may be a response, an exception to raise, or a
    function of the message history (to read earlier tool results, e.g. a slot_id).
    Once the script runs out it ends the turn quietly."""

    def __init__(self, steps: list[Step] | None = None):
        self.steps = list(steps or [])
        self.requests: list[dict[str, Any]] = []

    def create(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        self.requests.append(
            {"system": system, "messages": [dict(m) for m in messages], "tools": tools}
        )
        if not self.steps:
            return reply(text("done"))
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step(messages) if callable(step) else step

    @property
    def calls(self) -> int:
        return len(self.requests)
