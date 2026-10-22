"""Per-company runtime: the agent plus persistence, events and structured logs.

The agent stays pure. This layer wraps its adapters with hooks, so every message, tool call,
notification and state change is stored and streamed without the agent knowing about it.
"""

from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from leadagent.adapters import build_adapters
from leadagent.adapters.base import Adapters, Channel, Notifier
from leadagent.agent import LeadAgent
from leadagent.clock import Clock
from leadagent.config import load_company
from leadagent.config.schemas import CompanyBundle
from leadagent.llm import LLM
from leadagent.models import Lead, Message, Notification, ToolCall
from leadagent.server import views
from leadagent.server.events import EventBus
from leadagent.server.schemas import LeadDetail, LeadIn, LeadSummary
from leadagent.server.store import Store
from leadagent.session import LeadSession

log = logging.getLogger("leadagent.server")


class LLMUnavailable(RuntimeError):
    """No model is configured (for example ANTHROPIC_API_KEY is not set)."""


@dataclass
class Settings:
    database_path: str = "data/leadagent.db"
    default_company: str | None = None  # resolved from companies/ when unset
    webhook_secret: str | None = None
    adapter_env: Mapping[str, str] = field(default_factory=dict)
    cors_origins: list[str] = field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )

    @classmethod
    def from_env(cls, default_company: str | None = None) -> Settings:
        env = os.environ
        origins = [o.strip() for o in env.get("CORS_ORIGINS", "").split(",") if o.strip()]
        base = cls()
        return cls(
            database_path=env.get("DATABASE_PATH", base.database_path),
            default_company=default_company or env.get("DEFAULT_COMPANY") or None,
            webhook_secret=env.get("WEBHOOK_SECRET") or None,
            adapter_env=dict(env),
            cors_origins=origins or base.cors_origins,
        )


class HookedChannel:
    """Announces every outbound message that actually leaves the system."""

    def __init__(self, inner: Channel, on_send: Callable[[Lead, Message], None]):
        self.inner, self.on_send = inner, on_send
        self._local = threading.local()

    @contextmanager
    def sending_as(self, sender: str) -> Iterator[None]:
        self._local.sender = sender
        try:
            yield
        finally:
            self._local.sender = None

    def send(self, lead: Lead, body: str) -> Message:
        msg = self.inner.send(lead, body)
        sender = getattr(self._local, "sender", None)
        if sender:
            msg.sender = sender
        self.on_send(lead, msg)
        return msg


class RecordingNotifier:
    def __init__(self, inner: Notifier, on_notify: Callable[[Notification], None]):
        self.inner, self.on_notify = inner, on_notify

    def notify(self, notification: Notification) -> None:
        self.on_notify(notification)
        self.inner.notify(notification)


class CompanyRuntime:
    def __init__(
        self,
        slug: str,
        bundle: CompanyBundle,
        store: Store,
        bus: EventBus,
        clock: Clock,
        llm: LLM,
        env: Mapping[str, str],
        crm_path: str,
    ):
        self.slug, self.bundle, self.store, self.bus, self.clock = slug, bundle, store, bus, clock
        inner = build_adapters(
            bundle, clock, env, mock_crm_path=crm_path, mock_crm_table=f"crm_{slug}"
        )
        self.adapters = Adapters(
            channel=HookedChannel(inner.channel, self._on_send),
            crm=inner.crm,
            calendar=inner.calendar,
            notifier=RecordingNotifier(inner.notifier, self._on_notify),
        )
        self.agent = LeadAgent(
            bundle,
            self.adapters,
            llm,
            clock,
            record_tool=self._on_tool,
            on_message=self._on_inbound,
        )
        self.sessions: dict[str, LeadSession] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._first_response_sent: set[str] = set()
        self._rehydrate_calendar()

    # ------------------------------------------------------------------ plumbing
    def _pub(self, lead_id: str, type_: str, data: dict[str, Any]) -> None:
        self.bus.publish(self.slug, lead_id, type_, data, self.clock.now())

    def _lock_for(self, lead_id: str) -> threading.Lock:
        return self._locks.setdefault(lead_id, threading.Lock())

    def get_session(self, lead_id: str) -> LeadSession | None:
        s = self.sessions.get(lead_id)
        if s is not None:
            return s
        loaded = self.store.load_session(lead_id)
        if loaded is None or loaded[0] != self.slug:
            return None
        s = loaded[1]
        self.sessions[lead_id] = s
        if s.first_response_seconds is not None:
            self._first_response_sent.add(lead_id)
        return s

    def _rehydrate_calendar(self) -> None:
        """After a restart, re-mark booked slots so two leads can never share one."""
        bookings = getattr(self.adapters.calendar, "bookings", None)
        if bookings is None:
            return
        for lead_id in self.store.list_leads(self.slug, limit=100000):
            s = self.get_session(lead_id)
            if s and s.booking and s.booking.rep_id in bookings:
                bookings[s.booking.rep_id].append(s.booking)

    # --------------------------------------------------------------------- hooks
    def _on_send(self, lead: Lead, msg: Message) -> None:
        self._pub(lead.id, "message", msg.model_dump(mode="json"))

    def _on_inbound(self, session: LeadSession, msg: Message) -> None:
        if msg.direction == "inbound":
            self._pub(session.lead.id, "message", msg.model_dump(mode="json"))

    def _on_notify(self, n: Notification) -> None:
        self.store.add_notification(n)
        self._pub(n.lead_id, "notification", n.model_dump(mode="json"))

    def _on_tool(self, tc: ToolCall) -> None:
        self.store.add_tool_call(tc)
        self._pub(tc.lead_id, "tool_call", tc.model_dump(mode="json"))
        log.info(
            "tool_call",
            extra={
                "company": self.slug,
                "lead_id": tc.lead_id,
                "tool": tc.name,
                "latency_ms": tc.latency_ms,
                "error": tc.error,
            },
        )
        if tc.name == "send_message" and tc.result.get("blocked") == "quiet_hours":
            self._pub(tc.lead_id, "deferred", tc.result)
        session = self.sessions.get(tc.lead_id)
        if session is not None:
            self._sync(session)

    def _sync(self, session: LeadSession) -> None:
        lead_id = session.lead.id
        self.store.save_session(self.slug, session, self.clock.now())
        if session.first_response_seconds is not None and lead_id not in self._first_response_sent:
            self._first_response_sent.add(lead_id)
            self._pub(lead_id, "first_response", {"seconds": session.first_response_seconds})
            log.info(
                "first_response",
                extra={
                    "company": self.slug,
                    "lead_id": lead_id,
                    "first_response_seconds": session.first_response_seconds,
                },
            )
        self._pub(lead_id, "state", self.summary(session).model_dump(mode="json"))

    # ------------------------------------------------------------------- queries
    def summary(self, session: LeadSession) -> LeadSummary:
        return views.summarize(self.slug, session)

    def detail(self, session: LeadSession) -> LeadDetail:
        lead_id = session.lead.id
        return views.detail(
            self.slug,
            self.bundle,
            self.agent.router,
            session,
            self.store.notifications(lead_id),
            self.store.tool_calls(lead_id),
        )

    # ------------------------------------------------------------------ commands
    def create_lead(self, data: LeadIn) -> LeadSession:
        lead = Lead(
            id=f"ld_{uuid.uuid4().hex[:10]}",
            name=(data.name or "").strip() or None,
            phone=(data.phone or "").strip() or None,
            email=(data.email or "").strip() or None,
            source=data.source,
            message=data.message.strip(),
            created_at=self.clock.now(),
        )
        consent = "opted_in" if data.consent else None
        session = self.agent.open_session(lead, consent)
        self.sessions[lead.id] = session
        self.store.save_session(self.slug, session, self.clock.now())
        log.info(
            "lead_created",
            extra={"company": self.slug, "lead_id": lead.id, "source": lead.source},
        )
        self._pub(lead.id, "lead_created", lead.model_dump(mode="json"))
        self._pub(lead.id, "state", self.summary(session).model_dump(mode="json"))
        return session

    def _turn(self, lead_id: str, trigger: str, fn: Callable[[LeadSession], None]) -> None:
        session = self.get_session(lead_id)
        if session is None:
            return
        with self._lock_for(lead_id):
            started, t0 = self.clock.now(), time.perf_counter()
            try:
                fn(session)
            except Exception as e:
                log.exception("turn_failed", extra={"company": self.slug, "lead_id": lead_id})
                session.add_flag("agent_error")
                self._pub(lead_id, "error", {"message": f"{type(e).__name__}: {e}"})
            ms = round((time.perf_counter() - t0) * 1000, 1)
            self.store.add_turn(lead_id, trigger, started, self.clock.now(), ms)
            self._sync(session)
            self._pub(lead_id, "turn_done", {"duration_ms": ms, "trigger": trigger})
            log.info(
                "turn_done",
                extra={"company": self.slug, "lead_id": lead_id, "trigger": trigger, "ms": ms},
            )

    def run_first_turn(self, lead_id: str) -> None:
        self._turn(lead_id, "lead", self.agent.run_first_turn)

    def run_inbound(self, lead_id: str, text: str) -> None:
        self._turn(lead_id, "inbound", lambda s: self.agent.handle_inbound(s, text))

    def takeover(self, lead_id: str) -> LeadSession | None:
        session = self.get_session(lead_id)
        if session is None:
            return None
        with self._lock_for(lead_id):
            self.agent.takeover(session)
            self._sync(session)
        return session

    def human_message(self, lead_id: str, text: str) -> Message | None:
        """A person replies from the rep view. This also switches the agent off."""
        session = self.get_session(lead_id)
        if session is None:
            return None
        with self._lock_for(lead_id):
            if not session.human_takeover:
                self.agent.takeover(session)
            with self.adapters.channel.sending_as("human"):  # type: ignore[attr-defined]
                msg = self.adapters.channel.send(session.lead, text)
            session.messages.append(msg)
            self._sync(session)
        return msg

    def flush(self) -> int:
        """Deliver messages held back for quiet hours once they are allowed to go out."""
        delivered = 0
        for lead_id in self.store.leads_with_deferred(self.slug):
            session = self.get_session(lead_id)
            if session is None:
                continue
            with self._lock_for(lead_id):
                sent = self.agent.flush_deferred(session)
                if sent or not session.deferred:
                    self._sync(session)
                delivered += len(sent)
        return delivered


class _LazyLLM:
    """Defers building the real client until the agent first needs it, so read-only API calls
    work without an API key."""

    def __init__(self, manager: RuntimeManager):
        self.manager = manager

    def create(self, **kwargs: Any):
        return self.manager.get_llm().create(**kwargs)


class RuntimeManager:
    def __init__(
        self,
        settings: Settings,
        store: Store,
        bus: EventBus,
        clock: Clock,
        llm_factory: Callable[[], LLM] | None,
    ):
        self.settings, self.store, self.bus, self.clock = settings, store, bus, clock
        self._llm_factory = llm_factory
        self._llm: LLM | None = None
        self._runtimes: dict[str, CompanyRuntime] = {}
        self._lock = threading.Lock()

    unavailable_message = "ANTHROPIC_API_KEY is not set. Add it to .env to run the agent."

    def llm_ready(self) -> bool:
        return self._llm_factory is not None or bool(os.environ.get("ANTHROPIC_API_KEY"))

    def get_llm(self) -> LLM:
        if self._llm is None:
            if self._llm_factory is not None:
                self._llm = self._llm_factory()
            elif os.environ.get("ANTHROPIC_API_KEY"):
                from leadagent.llm import AnthropicLLM

                self._llm = AnthropicLLM()
            else:
                raise LLMUnavailable(self.unavailable_message)
        return self._llm

    def get(self, slug: str) -> CompanyRuntime:
        with self._lock:
            rt = self._runtimes.get(slug)
            if rt is None:
                bundle = load_company(slug)  # ConfigError propagates with a clear message
                db = self.settings.database_path
                rt = CompanyRuntime(
                    slug,
                    bundle,
                    self.store,
                    self.bus,
                    self.clock,
                    _LazyLLM(self),
                    self.settings.adapter_env,
                    crm_path=db if db != ":memory:" else ":memory:",
                )
                self._runtimes[slug] = rt
            return rt

    def for_lead(self, lead_id: str) -> CompanyRuntime:
        row = self.store.lead_row(lead_id)
        if row is None:
            raise KeyError(lead_id)
        return self.get(row["company"])

    def flush_all(self) -> int:
        with self._lock:
            runtimes = list(self._runtimes.values())
        return sum(rt.flush() for rt in runtimes)
