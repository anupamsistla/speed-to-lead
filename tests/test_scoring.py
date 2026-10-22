import pytest

from leadagent import scoring
from leadagent.models import Lead
from tests.conftest import HOT_FIELDS


def spec(bundle, key):
    return next(f for f in bundle.qualification.required_fields if f.key == key)


@pytest.mark.parametrize(
    ("key", "raw", "expected"),
    [
        ("monthly_bill", "$1,250.50 a month", 1250.5),
        ("monthly_bill", 180, 180.0),
        ("zip", "I'm in 80205!", "80205"),
        ("homeowner", "Owner", "owner"),
        ("roof_type", "asphalt shingle", "asphalt_shingle"),
        ("timeline", "One to three months", "one_to_three_months"),
    ],
)
def test_normalize(bundle, key, raw, expected):
    assert scoring.normalize_value(spec(bundle, key), raw) == expected


@pytest.mark.parametrize(
    ("key", "raw"),
    [("monthly_bill", "lots"), ("zip", "8020"), ("roof_type", "thatch"), ("zip", "")],
)
def test_normalize_rejects(bundle, key, raw):
    with pytest.raises(scoring.FieldError):
        scoring.normalize_value(spec(bundle, key), raw)


def values(**over):
    base = {
        "zip": "80205",
        "homeowner": "owner",
        "monthly_bill": 250.0,
        "roof_type": "asphalt_shingle",
        "timeline": "asap",
    }
    base.update(over)
    return base


def test_hot_lead_breakdown_sums_to_score(bundle):
    s = scoring.evaluate(bundle, values(email="a@b.co"))
    assert s.tier == "hot" and s.score == 100 and s.complete
    assert sum(i.points for i in s.breakdown) == s.score


def test_warm_and_cold(bundle):
    warm = scoring.evaluate(bundle, values(monthly_bill=150.0, timeline="three_to_six_months"))
    assert warm.tier == "warm" and warm.score == 60
    cold = scoring.evaluate(
        bundle,
        values(monthly_bill=100.0, timeline="researching", roof_type="other"),
    )
    assert cold.tier == "cold" and cold.score == 25


def test_bill_tiers_do_not_double_count(bundle):
    names = {i.rule for i in scoring.evaluate(bundle, values(monthly_bill=150.0)).breakdown}
    assert "bill_120_to_199" in names and "bill_200_plus" not in names


def test_renter_disqualified_with_close_message(bundle):
    s = scoring.evaluate(bundle, {"homeowner": "renter"})
    assert s.tier == "disqualified" and s.disqualified_by == "renter"
    assert s.close_message and not s.complete


def test_low_bill_disqualified(bundle):
    assert scoring.evaluate(bundle, values(monthly_bill=40.0)).disqualified_by == "low_bill"


def test_out_of_area_disqualified(bundle):
    s = scoring.evaluate(bundle, values(zip="10001"))
    assert s.tier == "disqualified" and s.disqualified_by == scoring.OUT_OF_AREA


def test_partial_is_provisional(bundle):
    s = scoring.evaluate(bundle, {"zip": "80205", "homeowner": "owner"})
    assert not s.complete
    assert set(s.missing_fields) == {"monthly_bill", "roof_type", "timeline"}


def test_session_values_include_contact_fields():
    from datetime import UTC, datetime

    from leadagent.session import LeadSession

    s = LeadSession(lead=Lead(id="x", email="a@b.co", created_at=datetime.now(UTC)))
    assert s.values()["email"] == "a@b.co"
    assert HOT_FIELDS["zip"] == "80205"
