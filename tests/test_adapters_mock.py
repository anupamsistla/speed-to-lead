from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from leadagent.adapters.mock import MockCalendar, MockChannel, MockCRM, MockNotifier
from leadagent.clock import FixedClock
from leadagent.models import Lead, Notification
from tests.conftest import BUSINESS_TIME, DENVER


@pytest.fixture
def cal(bundle, clock):
    hours = {r.id: r.business_hours for o in bundle.routing.offices for r in o.reps}
    return MockCalendar(hours, bundle.company.timezone, clock)


def lead(clock):
    return Lead(id="l1", name="Jamie", phone="+13035550142", created_at=clock.now())


def test_channel_records_outbound(clock):
    ch = MockChannel(clock)
    m = ch.send(lead(clock), "hi")
    assert m.direction == "outbound" and ch.outbox == [m]


def test_crm_matches_phone_across_formats_and_email_case():
    crm = MockCRM()
    c = crm.seed_contact(name="A", phone="(303) 555-0142", email="A@Example.com")
    assert crm.find_contact(phone="+1 303-555-0142", email=None).id == c.id
    assert crm.find_contact(phone=None, email="a@example.COM").id == c.id
    assert crm.find_contact(phone="303-555-9999", email="other@x.co") is None
    assert crm.find_contact(phone=None, email=None) is None


def test_crm_upsert_merges_properties_and_updates_stage():
    crm = MockCRM()
    a = crm.upsert_contact(
        name="A", phone="3035550142", email=None, properties={"x": 1}, pipeline="P", stage="New"
    )
    b = crm.upsert_contact(
        name=None,
        phone="3035550142",
        email="a@b.co",
        properties={"y": 2},
        pipeline="P",
        stage="Booked",
    )
    assert a.id == b.id
    assert b.properties == {"x": 1, "y": 2} and b.stage == "Booked"
    assert b.name == "A" and b.email == "a@b.co"
    crm.update_stage(a.id, pipeline="P", stage="Won")
    assert crm.get(a.id).stage == "Won"
    with pytest.raises(KeyError):
        crm.update_stage("nope", pipeline="P", stage="x")


def test_notifier_collects(clock):
    n = MockNotifier()
    note = Notification(
        kind="new_lead", channel="#c", title="t", lead_id="l", created_at=clock.now()
    )
    n.notify(note)
    assert n.sent == [note]


def test_calendar_slots_respect_business_hours(cal, bundle):
    # maya_ortiz: Mon-Fri 08-17, Sat 09-13. Look at Tue Oct 27 only.
    start = datetime(2026, 10, 27, 0, 0, tzinfo=DENVER)
    slots = cal.get_slots(
        ["maya_ortiz"], start=start, end=start + timedelta(days=1), duration_minutes=60
    )
    times = [s.start.strftime("%H:%M") for s in slots]
    assert times[0] == "08:00" and times[-1] == "16:00"
    assert len(times) == 17  # 30-minute grid from 08:00 through 16:00
    assert all(s.end - s.start == timedelta(minutes=60) for s in slots)


def test_calendar_closed_days(cal):
    sunday = datetime(2026, 11, 1, 0, 0, tzinfo=DENVER)
    assert (
        cal.get_slots(
            ["maya_ortiz"], start=sunday, end=sunday + timedelta(days=1), duration_minutes=60
        )
        == []
    )
    # dan_whitaker has no Saturday hours, maya_ortiz does
    sat = datetime(2026, 10, 31, 0, 0, tzinfo=DENVER)
    assert (
        cal.get_slots(["dan_whitaker"], start=sat, end=sat + timedelta(days=1), duration_minutes=60)
        == []
    )
    assert cal.get_slots(
        ["maya_ortiz"], start=sat, end=sat + timedelta(days=1), duration_minutes=60
    )


def test_calendar_booking_blocks_overlaps_only_for_that_rep(cal, clock):
    day = datetime(2026, 10, 27, 0, 0, tzinfo=DENVER)
    reps = ["maya_ortiz", "dan_whitaker"]
    first = cal.get_slots(reps, start=day, end=day + timedelta(days=1), duration_minutes=60)[0]
    assert first.rep_id == "maya_ortiz" and first.start.hour == 8
    cal.book(
        slot=first,
        lead=lead(clock),
        office_id="denver",
        office_name="Denver",
        rep_name="Maya",
        kind="k",
    )
    again = cal.get_slots(reps, start=day, end=day + timedelta(days=1), duration_minutes=60)
    by_time = {s.start.strftime("%H:%M"): s.rep_id for s in again}
    assert "08:00" not in by_time and "08:30" not in by_time  # maya busy, dan not yet open
    assert by_time["09:00"] == "maya_ortiz"  # her booking ended at 09:00
    nine = next(s for s in again if s.start.strftime("%H:%M") == "09:00")
    cal.book(
        slot=nine,
        lead=lead(clock),
        office_id="denver",
        office_name="Denver",
        rep_name="Maya",
        kind="k",
    )
    later = cal.get_slots(reps, start=day, end=day + timedelta(days=1), duration_minutes=60)
    assert {s.start.strftime("%H:%M"): s.rep_id for s in later}["09:00"] == "dan_whitaker"
    with pytest.raises(ValueError):
        cal.book(
            slot=first,
            lead=lead(clock),
            office_id="denver",
            office_name="Denver",
            rep_name="Maya",
            kind="k",
        )


def test_calendar_slot_must_end_inside_hours(cal):
    start = datetime(2026, 10, 27, 16, 30, tzinfo=DENVER)
    assert not cal.is_free("dan_whitaker", start, 60)  # 16:30-17:30 runs past 17:00
    assert cal.is_free("dan_whitaker", datetime(2026, 10, 27, 16, 0, tzinfo=DENVER), 60)


def test_calendar_rep_order_sets_priority(cal):
    day = datetime(2026, 10, 27, 0, 0, tzinfo=DENVER)
    slots = cal.get_slots(
        ["dan_whitaker", "priya_nair"], start=day, end=day + timedelta(days=1), duration_minutes=60
    )
    assert {s.rep_id for s in slots} == {"dan_whitaker"}


def test_fixed_clock_requires_aware():
    with pytest.raises(ValueError):
        FixedClock(datetime(2026, 1, 1))
    assert BUSINESS_TIME.tzinfo == ZoneInfo("America/Denver")
