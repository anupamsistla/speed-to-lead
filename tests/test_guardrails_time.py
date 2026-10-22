from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from leadagent.guardrails import in_quiet_hours, quiet_hours_end

DEN = ZoneInfo("America/Denver")


@pytest.mark.parametrize(
    ("hour", "minute", "expected"),
    [
        (8, 0, False),
        (12, 0, False),
        (20, 59, False),
        (21, 0, True),
        (23, 59, True),
        (0, 0, True),
        (7, 59, True),
    ],
)
def test_quiet_hours_wrap_midnight(bundle, hour, minute, expected):
    now = datetime(2026, 10, 27, hour, minute, tzinfo=DEN)
    assert in_quiet_hours(bundle.company, now) is expected


def test_quiet_hours_use_company_timezone_not_utc(bundle):
    # 03:00 UTC is 21:00 in Denver (MDT), which is quiet. 15:00 UTC is 09:00, not quiet.
    assert in_quiet_hours(bundle.company, datetime(2026, 10, 28, 3, 0, tzinfo=ZoneInfo("UTC")))
    assert not in_quiet_hours(bundle.company, datetime(2026, 10, 27, 15, 0, tzinfo=ZoneInfo("UTC")))


def test_quiet_hours_end_next_morning(bundle):
    late = datetime(2026, 10, 27, 22, 30, tzinfo=DEN)
    assert quiet_hours_end(bundle.company, late) == datetime(2026, 10, 28, 8, 0, tzinfo=DEN)
    early = datetime(2026, 10, 27, 3, 0, tzinfo=DEN)
    assert quiet_hours_end(bundle.company, early) == datetime(2026, 10, 27, 8, 0, tzinfo=DEN)
    noon = datetime(2026, 10, 27, 12, 0, tzinfo=DEN)
    assert quiet_hours_end(bundle.company, noon) == noon
