"""FastAPI app: lead intake, company config, lead detail, SSE streams, clock control."""

from __future__ import annotations

import asyncio
import hmac
import logging
import mimetypes
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from leadagent.clock import Clock, OffsetClock
from leadagent.config import ConfigError, list_companies, load_company
from leadagent.config.loader import REPO_ROOT
from leadagent.config.schemas import CompanyBundle
from leadagent.llm import LLM
from leadagent.models import Message
from leadagent.server.events import EventBus
from leadagent.server.logging_setup import configure_logging
from leadagent.server.runtime import CompanyRuntime, RuntimeManager, Settings
from leadagent.server.schemas import (
    Accepted,
    ClockIn,
    ClockOut,
    CompanyBrief,
    CompanyList,
    CompanyPublicConfig,
    EventHistory,
    Health,
    HumanMessageIn,
    InboundMessageIn,
    LeadDetail,
    LeadIn,
    LeadList,
    LeadSummary,
    MissedCallWebhook,
    OfficeBrief,
    QualificationFieldView,
    SmsWebhook,
    StreamEvent,
    WebFormWebhook,
)
from leadagent.server.store import Store

log = logging.getLogger("leadagent.server")
WEB_DIST = REPO_ROOT / "web" / "dist"


def _sse(ev: StreamEvent) -> str:
    return f"id: {ev.id}\nevent: {ev.type}\ndata: {ev.model_dump_json()}\n\n"


def _logo_url(slug: str) -> str:
    return f"/api/companies/{slug}/logo"


def public_config(bundle: CompanyBundle, slug: str) -> CompanyPublicConfig:
    c, q, r = bundle.company, bundle.qualification, bundle.routing
    return CompanyPublicConfig(
        slug=slug,
        name=c.name,
        description=" ".join(c.description.split()),
        brand_color=c.brand_color,
        logo_url=_logo_url(slug),
        timezone=c.timezone,
        tone=" ".join(c.tone.split()),
        reply_signature=c.reply_signature,
        hot_lead_threshold=q.hot_lead_threshold,
        appointment_kind=r.appointment.kind,
        appointment_minutes=r.appointment.duration_minutes,
        fields=[
            QualificationFieldView(key=f.key, question=f.question, type=f.type, options=f.options)
            for f in q.required_fields
        ],
        offices=[OfficeBrief(id=o.id, name=o.name, reps=len(o.reps)) for o in r.offices],
        slack_channel=r.slack_channel,
        crm_pipeline=bundle.crm_mapping.pipeline,
    )


def create_app(
    settings: Settings | None = None,
    *,
    llm_factory: Callable[[], LLM] | None = None,
    clock: Clock | None = None,
    load_env: bool = True,
    flush_interval: float = 5.0,
) -> FastAPI:
    if load_env:
        load_dotenv(REPO_ROOT / ".env")
    configure_logging()
    settings = settings or Settings.from_env()
    store = Store(settings.database_path)
    bus = EventBus(store)
    clock = clock or OffsetClock()
    manager = RuntimeManager(settings, store, bus, clock, llm_factory)

    def default_company() -> str:
        if settings.default_company:
            return settings.default_company
        available = list_companies()
        if not available:
            raise HTTPException(500, "no companies found under companies/")
        return available[0]

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        async def flusher() -> None:
            while True:
                await asyncio.sleep(flush_interval)
                try:
                    await asyncio.to_thread(manager.flush_all)
                except Exception:
                    log.exception("flush_failed")

        task = asyncio.create_task(flusher())
        try:
            yield
        finally:
            task.cancel()

    app = FastAPI(
        title="Speed-to-Lead Agent",
        version="0.1.0",
        description="Intake, agent state and live event streams for the demo UI.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.manager, app.state.store, app.state.bus, app.state.clock = (
        manager,
        store,
        bus,
        clock,
    )

    # ------------------------------------------------------------------ helpers
    def runtime(slug: str) -> CompanyRuntime:
        try:
            return manager.get(slug)
        except ConfigError as e:
            if "no folder" in str(e):
                raise HTTPException(404, f"unknown company '{slug}'") from e
            raise HTTPException(422, {"company": slug, "problems": e.problems}) from e

    def runtime_for_lead(lead_id: str) -> tuple[CompanyRuntime, object]:
        try:
            rt = manager.for_lead(lead_id)
        except KeyError as e:
            raise HTTPException(404, f"unknown lead '{lead_id}'") from e
        except ConfigError as e:
            raise HTTPException(503, str(e)) from e
        session = rt.get_session(lead_id)
        if session is None:
            raise HTTPException(404, f"unknown lead '{lead_id}'")
        return rt, session

    def require_secret(x_webhook_secret: str | None = Header(default=None)) -> None:
        if settings.webhook_secret and not hmac.compare_digest(
            x_webhook_secret or "", settings.webhook_secret
        ):
            raise HTTPException(401, "invalid webhook secret")

    def make_lead(**kwargs: object) -> LeadIn:
        try:
            return LeadIn(**kwargs)  # type: ignore[arg-type]
        except ValidationError as e:
            raise HTTPException(422, e.errors(include_url=False, include_context=False)) from e

    def need_llm() -> None:
        if not manager.llm_ready():
            raise HTTPException(503, manager.unavailable_message)

    def accept(data: LeadIn, background: BackgroundTasks) -> Accepted:
        need_llm()
        rt = runtime(data.company or default_company())
        session = rt.create_lead(data)
        background.add_task(rt.run_first_turn, session.lead.id)
        return Accepted(lead_id=session.lead.id, created_at=session.lead.created_at)

    # ------------------------------------------------------------------- system
    @app.get("/api/health", response_model=Health, tags=["system"])
    def health() -> Health:
        env = settings.adapter_env
        return Health(
            ok=True,
            llm="ready" if manager.llm_ready() else "missing_api_key",
            model=env.get("ANTHROPIC_MODEL") or "claude-sonnet-5-5",
            adapters={
                k.removesuffix("_ADAPTER").lower(): (env.get(k) or "mock")
                for k in ("CHANNEL_ADAPTER", "CRM_ADAPTER", "CALENDAR_ADAPTER", "NOTIFIER_ADAPTER")
            },
            simulated_clock=bool(getattr(clock, "simulated", False)),
        )

    @app.get("/api/clock", response_model=ClockOut, tags=["system"])
    def get_clock() -> ClockOut:
        return ClockOut(now=clock.now(), simulated=bool(getattr(clock, "simulated", False)))

    @app.put("/api/clock", response_model=ClockOut, tags=["system"])
    def set_clock(body: ClockIn) -> ClockOut:
        """Pretend it is a different time (for example 11pm to demo quiet hours)."""
        if not hasattr(clock, "set"):
            raise HTTPException(409, "this clock cannot be changed")
        try:
            clock.set(body.now)  # type: ignore[attr-defined]
        except ValueError as e:
            raise HTTPException(422, str(e)) from e
        return get_clock()

    # ---------------------------------------------------------------- companies
    @app.get("/api/companies", response_model=CompanyList, tags=["companies"])
    def companies() -> CompanyList:
        briefs = []
        for slug in list_companies():
            try:
                b = load_company(slug)
            except ConfigError as e:
                log.warning("company_invalid", extra={"company": slug, "problems": e.problems})
                continue
            briefs.append(
                CompanyBrief(
                    slug=slug,
                    name=b.company.name,
                    brand_color=b.company.brand_color,
                    logo_url=_logo_url(slug),
                )
            )
        return CompanyList(default=default_company(), companies=briefs)

    @app.get("/api/companies/{slug}/config", response_model=CompanyPublicConfig, tags=["companies"])
    def company_config(slug: str) -> CompanyPublicConfig:
        try:
            return public_config(load_company(slug), slug)
        except ConfigError as e:
            if "no folder" in str(e):
                raise HTTPException(404, f"unknown company '{slug}'") from e
            raise HTTPException(422, {"company": slug, "problems": e.problems}) from e

    @app.get("/api/companies/{slug}/logo", tags=["companies"])
    def company_logo(slug: str):
        try:
            b = load_company(slug)
        except ConfigError as e:
            raise HTTPException(404, f"unknown company '{slug}'") from e
        logo = b.company.logo
        if logo.startswith(("http://", "https://")):
            return RedirectResponse(logo)
        root = Path(b.root).resolve()
        path = (root / logo).resolve()
        if root not in path.parents or not path.is_file():
            raise HTTPException(404, "logo not found")
        return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "image/png")

    # -------------------------------------------------------------------- leads
    @app.post("/api/leads", response_model=Accepted, status_code=202, tags=["leads"])
    def create_lead(data: LeadIn, background: BackgroundTasks) -> Accepted:
        """Submit a lead. Returns immediately; the agent replies in the background."""
        return accept(data, background)

    @app.get("/api/leads", response_model=LeadList, tags=["leads"])
    def list_leads(company: str | None = None, limit: int = Query(50, le=200)) -> LeadList:
        company = company or default_company()
        rt = runtime(company)
        out: list[LeadSummary] = []
        for lead_id in store.list_leads(company, limit):
            s = rt.get_session(lead_id)
            if s:
                out.append(rt.summary(s))
        return LeadList(leads=out)

    @app.get("/api/leads/{lead_id}", response_model=LeadDetail, tags=["leads"])
    def lead_detail(lead_id: str) -> LeadDetail:
        rt, session = runtime_for_lead(lead_id)
        return rt.detail(session)  # type: ignore[arg-type]

    @app.post(
        "/api/leads/{lead_id}/messages", response_model=Accepted, status_code=202, tags=["leads"]
    )
    def lead_reply(lead_id: str, body: InboundMessageIn, background: BackgroundTasks) -> Accepted:
        """A reply from the lead (simulated inbound SMS)."""
        need_llm()
        rt, session = runtime_for_lead(lead_id)
        background.add_task(rt.run_inbound, lead_id, body.text)
        return Accepted(lead_id=lead_id, created_at=session.lead.created_at)  # type: ignore[attr-defined]

    @app.post("/api/leads/{lead_id}/takeover", response_model=LeadSummary, tags=["leads"])
    def takeover(lead_id: str) -> LeadSummary:
        """A human takes over. The agent stops replying to this lead."""
        rt, _ = runtime_for_lead(lead_id)
        session = rt.takeover(lead_id)
        assert session is not None
        return rt.summary(session)

    @app.post("/api/leads/{lead_id}/human-message", response_model=Message, tags=["leads"])
    def human_message(lead_id: str, body: HumanMessageIn) -> Message:
        """A person replies to the lead from the rep view (also takes over)."""
        rt, _ = runtime_for_lead(lead_id)
        msg = rt.human_message(lead_id, body.text)
        if msg is None:
            raise HTTPException(404, f"unknown lead '{lead_id}'")
        return msg

    # ------------------------------------------------------------------- events
    @app.get("/api/leads/{lead_id}/events/history", response_model=EventHistory, tags=["events"])
    def lead_event_history(lead_id: str, after: int = 0) -> EventHistory:
        runtime_for_lead(lead_id)
        return EventHistory(events=bus.history(lead_id=lead_id, after=after))

    async def stream(
        request: Request, lead_id: str | None, company: str | None, after: int, follow: bool
    ) -> AsyncIterator[str]:
        sub = bus.subscribe(lead_id=lead_id, company=company)  # subscribe first: no gaps
        try:
            last = after
            for ev in await asyncio.to_thread(
                bus.history, lead_id=lead_id, company=company, after=after
            ):
                yield _sse(ev)
                last = ev.id
            if not follow:
                return
            while not await request.is_disconnected():
                try:
                    ev = await asyncio.wait_for(sub.queue.get(), timeout=15)
                except TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                if ev.id > last:
                    yield _sse(ev)
                    last = ev.id
        finally:
            bus.unsubscribe(sub)

    def sse_response(gen: AsyncIterator[str]) -> StreamingResponse:
        return StreamingResponse(
            gen,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get(
        "/api/leads/{lead_id}/events",
        tags=["events"],
        responses={200: {"content": {"text/event-stream": {}}, "description": "StreamEvent items"}},
    )
    async def lead_events(
        request: Request,
        lead_id: str,
        follow: bool = True,
        after: int = 0,
        last_event_id: str | None = Header(default=None),
    ):
        """Server-sent events for one lead. Replays from `after` (or Last-Event-ID), then
        follows live. Each event's data is a StreamEvent."""
        runtime_for_lead(lead_id)
        cursor = int(last_event_id) if last_event_id and last_event_id.isdigit() else after
        return sse_response(stream(request, lead_id, None, cursor, follow))

    @app.get("/api/events", tags=["events"])
    async def company_events(
        request: Request,
        company: str | None = None,
        follow: bool = True,
        after: int = 0,
        last_event_id: str | None = Header(default=None),
    ):
        """Server-sent events for every lead of a company."""
        cursor = int(last_event_id) if last_event_id and last_event_id.isdigit() else after
        return sse_response(stream(request, None, company or default_company(), cursor, follow))

    # ------------------------------------------------------------ intake webhooks
    @app.post(
        "/api/intake/web-form",
        response_model=Accepted,
        status_code=202,
        tags=["intake"],
        dependencies=[Depends(require_secret)],
    )
    def intake_web_form(
        body: WebFormWebhook, background: BackgroundTasks, company: str | None = None
    ) -> Accepted:
        """Webhook for a website form. Protect with the X-Webhook-Secret header."""
        data = make_lead(company=company, source="web_form", **body.model_dump())
        return accept(data, background)

    @app.post(
        "/api/intake/missed-call",
        response_model=Accepted,
        status_code=202,
        tags=["intake"],
        dependencies=[Depends(require_secret)],
    )
    def intake_missed_call(
        body: MissedCallWebhook, background: BackgroundTasks, company: str | None = None
    ) -> Accepted:
        """Webhook for a missed call. The agent texts the caller back."""
        data = make_lead(
            company=company, source="missed_call", phone=body.from_number, name=body.name
        )
        return accept(data, background)

    @app.post(
        "/api/intake/sms",
        response_model=Accepted,
        status_code=202,
        tags=["intake"],
        dependencies=[Depends(require_secret)],
    )
    def intake_sms(
        body: SmsWebhook, background: BackgroundTasks, company: str | None = None
    ) -> Accepted:
        """Inbound text. Continues the lead's conversation if the number is known."""
        need_llm()
        slug = company or default_company()
        rt = runtime(slug)
        existing = store.find_lead_by_phone(slug, body.from_number)
        if existing:
            session = rt.get_session(existing)
            if session is not None:
                background.add_task(rt.run_inbound, existing, body.body)
                return Accepted(lead_id=existing, created_at=session.lead.created_at)
        data = make_lead(
            company=slug, source="text", phone=body.from_number, message=body.body, name=body.name
        )
        return accept(data, background)

    if WEB_DIST.is_dir():
        app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")

    return app
