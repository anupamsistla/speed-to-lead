"""Event fan-out for Server-Sent Events.

Events are persisted first (so the id is a durable replay cursor), then pushed to live
subscribers. Agent code runs in worker threads, so pushes cross into each subscriber's event
loop with call_soon_threadsafe.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime
from typing import Any

from leadagent.server.schemas import StreamEvent
from leadagent.server.store import Store


class Subscriber:
    def __init__(self, lead_id: str | None, company: str | None):
        self.lead_id = lead_id
        self.company = company
        self.loop = asyncio.get_running_loop()
        self.queue: asyncio.Queue[StreamEvent] = asyncio.Queue()

    def wants(self, ev: StreamEvent) -> bool:
        return (self.lead_id is None or ev.lead_id == self.lead_id) and (
            self.company is None or ev.company == self.company
        )

    def push(self, ev: StreamEvent) -> None:
        try:
            self.loop.call_soon_threadsafe(self.queue.put_nowait, ev)
        except RuntimeError:  # loop already closed (shutdown)
            pass


class EventBus:
    def __init__(self, store: Store):
        self.store = store
        self._subs: list[Subscriber] = []
        self._lock = threading.Lock()

    def publish(
        self, company: str, lead_id: str, type_: str, data: dict[str, Any], at: datetime
    ) -> StreamEvent:
        seq = self.store.add_event(lead_id, company, type_, data, at)
        ev = StreamEvent(
            id=seq,
            type=type_,
            lead_id=lead_id,
            company=company,
            at=at,
            data=data,  # type: ignore[arg-type]
        )
        with self._lock:
            subs = [s for s in self._subs if s.wants(ev)]
        for s in subs:
            s.push(ev)
        return ev

    def subscribe(self, lead_id: str | None = None, company: str | None = None) -> Subscriber:
        sub = Subscriber(lead_id, company)
        with self._lock:
            self._subs.append(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        with self._lock:
            if sub in self._subs:
                self._subs.remove(sub)

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    def history(
        self, *, lead_id: str | None = None, company: str | None = None, after: int = 0
    ) -> list[StreamEvent]:
        rows = self.store.events(lead_id=lead_id, company=company, after=after)
        return [StreamEvent.model_validate(row) for row in rows]
