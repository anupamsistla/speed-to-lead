"""Injectable clock so quiet hours, slots and evals are deterministic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    def __init__(self, now: datetime):
        if now.tzinfo is None:
            raise ValueError("FixedClock needs an aware datetime")
        self._now = now

    def now(self) -> datetime:
        return self._now

    def set(self, now: datetime) -> None:
        self._now = now

    def advance(self, **kwargs: float) -> None:
        self._now += timedelta(**kwargs)


class OffsetClock:
    """Real time plus an offset, so a demo can pretend it is 11pm and keep ticking from there."""

    def __init__(self) -> None:
        self._offset = timedelta(0)
        self.simulated = False

    def now(self) -> datetime:
        return datetime.now(UTC) + self._offset

    def set(self, target: datetime | None) -> None:
        if target is None:
            self._offset, self.simulated = timedelta(0), False
            return
        if target.tzinfo is None:
            raise ValueError("simulated time needs a timezone offset")
        self._offset, self.simulated = target - datetime.now(UTC), True
