"""Deterministic qualification, scoring and tiering driven entirely by qualification.yaml."""

from __future__ import annotations

import re
from typing import Any

from leadagent.config.schemas import (
    CompanyBundle,
    Condition,
    FieldSpec,
    QualificationConfig,
)
from leadagent.models import Score, ScoreItem

OUT_OF_AREA = "out_of_area"


class FieldError(ValueError):
    pass


def normalize_value(spec: FieldSpec, raw: Any) -> Any:
    """Coerce a model- or lead-supplied value to the field's declared type."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        raise FieldError(f"{spec.key}: empty value")
    if spec.type == "number":
        if isinstance(raw, bool):
            raise FieldError(f"{spec.key}: expected a number")
        if isinstance(raw, int | float):
            return float(raw)
        m = re.search(r"-?\d[\d,]*\.?\d*", str(raw))
        if not m:
            raise FieldError(f"{spec.key}: expected a number, got {raw!r}")
        return float(m.group(0).replace(",", ""))
    if spec.type == "boolean":
        if isinstance(raw, bool):
            return raw
        s = str(raw).strip().lower()
        if s in {"yes", "y", "true", "1"}:
            return True
        if s in {"no", "n", "false", "0"}:
            return False
        raise FieldError(f"{spec.key}: expected yes or no, got {raw!r}")
    if spec.type == "zip":
        m = re.search(r"\b(\d{5})\b", str(raw))
        if not m:
            raise FieldError(f"{spec.key}: expected a 5-digit zip, got {raw!r}")
        return m.group(1)
    if spec.type == "choice":
        s = str(raw).strip().lower().replace("+", "_plus").replace(" ", "_").replace("-", "_")
        s = re.sub(r"_+", "_", s).strip("_")
        for opt in spec.options:
            if s == opt.lower():
                return opt
        raise FieldError(f"{spec.key}: {raw!r} is not one of {spec.options}")
    return str(raw).strip()


def _holds(cond: Condition, values: dict[str, Any]) -> bool:
    v = values.get(cond.field)
    if cond.op == "exists":
        return v not in (None, "")
    if v is None:
        return False
    try:
        match cond.op:
            case "eq":
                return v == cond.value
            case "neq":
                return v != cond.value
            case "in":
                return v in cond.value
            case "not_in":
                return v not in cond.value
            case "lt":
                return v < cond.value
            case "lte":
                return v <= cond.value
            case "gt":
                return v > cond.value
            case "gte":
                return v >= cond.value
            case "contains":
                return str(cond.value).lower() in str(v).lower()
    except TypeError:
        return False
    return False


def missing_fields(q: QualificationConfig, values: dict[str, Any]) -> list[str]:
    return [k for k in q.field_keys if values.get(k) in (None, "")]


def evaluate(bundle: CompanyBundle, values: dict[str, Any]) -> Score:
    """Score a lead from known values (qualification fields plus contact fields)."""
    q = bundle.qualification
    missing = missing_fields(q, values)

    zip_code = values.get("zip")
    if zip_code and zip_code not in set(bundle.company.service_area_zips):
        return Score(
            score=0,
            tier="disqualified",
            complete=not missing,
            missing_fields=missing,
            disqualified_reason=f"Zip {zip_code} is outside the service area.",
            disqualified_by=OUT_OF_AREA,
        )

    for rule in q.disqualify_if:
        if all(_holds(c, values) for c in rule.when):
            return Score(
                score=0,
                tier="disqualified",
                complete=not missing,
                missing_fields=missing,
                disqualified_reason=rule.reason,
                disqualified_by=rule.name,
                close_message=rule.close_message,
            )

    items = [
        ScoreItem(rule=r.name, points=r.points)
        for r in q.score_weights
        if all(_holds(c, values) for c in r.when)
    ]
    total = max(0, sum(i.points for i in items))
    if total >= q.hot_lead_threshold:
        tier = "hot"
    elif total >= q.warm_lead_threshold:
        tier = "warm"
    else:
        tier = "cold"
    return Score(
        score=total, tier=tier, breakdown=items, complete=not missing, missing_fields=missing
    )
