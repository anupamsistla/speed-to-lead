"""Aggregate scenario results into the headline metrics."""

from __future__ import annotations

import math
from typing import Any

from leadagent.evals.runner import ScenarioResult


def percentile(values: list[float], p: float) -> float | None:
    """Linear-interpolated percentile (p in 0..100)."""
    if not values:
        return None
    xs = sorted(values)
    k = (len(xs) - 1) * p / 100
    lo, hi = math.floor(k), math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def _rate(flags: list[bool]) -> float | None:
    return round(sum(flags) / len(flags), 4) if flags else None


def aggregate(results: list[ScenarioResult]) -> dict[str, Any]:
    def checks(name: str) -> list[bool]:
        return [r.checks[name] for r in results if r.checks.get(name) is not None]  # type: ignore[misc]

    first = [r.first_response_seconds for r in results if r.first_response_seconds is not None]
    wanted_booked = [r for r in results if r.checks.get("expected_booking") is True]
    judged = [v.passed for r in results for v in r.judge]
    med, p95 = percentile(first, 50), percentile(first, 95)
    return {
        "runs": len(results),
        "passed": sum(r.passed for r in results),
        "pass_rate": _rate([r.passed for r in results]),
        "first_response_median_s": round(med, 2) if med is not None else None,
        "first_response_p95_s": round(p95, 2) if p95 is not None else None,
        "first_response_samples": len(first),
        "qualification_accuracy": _rate(checks("qualification")),
        "routing_accuracy": _rate(checks("routing")),
        "booking_rate": _rate([bool(r.outcome.get("booked")) for r in wanted_booked]),
        "booking_accuracy": _rate(checks("booking")),
        "guardrail_violations": sum(len(r.violations) for r in results),
        "backstops_used": sum(len(r.backstops) for r in results),
        "judge_pass_rate": _rate(judged),
        "judge_checks": len(judged),
        "crashed": sum(r.error is not None for r in results),
    }
