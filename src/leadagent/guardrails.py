"""Deterministic guardrail helpers enforced in code, not just in the prompt."""

from __future__ import annotations

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
