"""Pydantic schemas for everything under companies/<slug>/.

The engine only ever sees these models. Anything company specific is data.
"""

from __future__ import annotations

import re
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")

# Fields every lead carries from intake, usable in qualification conditions.
CONTACT_FIELDS = ("name", "phone", "email", "source")

# Internal keys the engine writes to the CRM. summary and lead_score must be mapped.
CORE_CRM_FIELDS = (
    "summary",
    "lead_score",
    "score_tier",
    "assigned_office",
    "assigned_rep",
    "appointment_time",
    "consent_status",
    "source",
)
REQUIRED_CRM_FIELDS = ("summary", "lead_score")

_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_WINDOW = re.compile(r"^([01]\d|2[0-3]):[0-5]\d-([01]\d|2[0-3]):[0-5]\d$")
_ZIP = re.compile(r"^\d{5}$")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9_]*$")


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _check_hhmm(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError(
            f'must be a quoted "HH:MM" string (got {value!r}). '
            "Unquoted 21:00 is parsed by YAML as a number."
        )
    if not _HHMM.match(value):
        raise ValueError(f'"{value}" is not a valid HH:MM time')
    return value


def expand_zips(items: list[str]) -> list[str]:
    """Expand entries like "80202-80212" into individual 5-digit zips, keeping order."""
    out: list[str] = []
    for raw in items:
        item = str(raw).strip()
        if "-" in item:
            lo, _, hi = item.partition("-")
            if not (_ZIP.match(lo) and _ZIP.match(hi) and int(lo) <= int(hi)):
                raise ValueError(f'"{item}" is not a valid zip range like "80202-80212"')
            out.extend(f"{z:05d}" for z in range(int(lo), int(hi) + 1))
        elif _ZIP.match(item):
            out.append(item)
        else:
            raise ValueError(f'"{item}" is not a 5-digit zip')
    seen: set[str] = set()
    return [z for z in out if not (z in seen or seen.add(z))]


class BusinessHours(Strict):
    """Per-weekday open window as "HH:MM-HH:MM". Missing or null means closed."""

    mon: str | None = None
    tue: str | None = None
    wed: str | None = None
    thu: str | None = None
    fri: str | None = None
    sat: str | None = None
    sun: str | None = None

    @field_validator(*WEEKDAYS)
    @classmethod
    def _window(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not isinstance(v, str) or not _WINDOW.match(v):
            raise ValueError(f'"{v}" must look like "09:00-17:00"')
        start, end = v.split("-")
        if start >= end:
            raise ValueError(f'"{v}": start must be before end')
        return v

    def window(self, weekday: str) -> tuple[str, str] | None:
        raw = getattr(self, weekday)
        if raw is None:
            return None
        start, end = raw.split("-")
        return start, end


class QuietHours(Strict):
    """No outbound messages between start and end (may wrap midnight), in company timezone."""

    start: str
    end: str

    @field_validator("start", "end", mode="before")
    @classmethod
    def _t(cls, v: Any) -> str:
        return _check_hhmm(v)


class CompanyConfig(Strict):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    tone: str = Field(min_length=1)
    reply_signature: str = Field(min_length=1)
    timezone: str
    business_hours: BusinessHours
    quiet_hours: QuietHours
    service_area_zips: list[str] = Field(min_length=1)
    logo: str = Field(min_length=1)
    brand_color: str

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as e:
            raise ValueError(f'unknown timezone "{v}" (use an IANA name)') from e
        return v

    @field_validator("service_area_zips", mode="before")
    @classmethod
    def _zips(cls, v: Any) -> list[str]:
        if not isinstance(v, list):
            raise ValueError("must be a list")
        return expand_zips([str(x) for x in v])

    @field_validator("brand_color")
    @classmethod
    def _color(cls, v: str) -> str:
        if not re.match(r"^#[0-9a-fA-F]{6}$", v):
            raise ValueError(f'"{v}" must be a hex color like "#F59E0B"')
        return v


# ---------------------------------------------------------------- qualification

FieldType = Literal["text", "choice", "number", "boolean", "zip"]
Op = Literal["eq", "neq", "in", "not_in", "lt", "lte", "gt", "gte", "contains", "exists"]


class FieldSpec(Strict):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    question: str = Field(min_length=1)
    type: FieldType = "text"
    options: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _choice_needs_options(self) -> FieldSpec:
        if self.type == "choice" and not self.options:
            raise ValueError(f'field "{self.key}" is type choice but has no options')
        bad = [o for o in self.options if not re.fullmatch(r"[a-z0-9][a-z0-9_]*", o)]
        if bad:
            raise ValueError(
                f'field "{self.key}" options must be lowercase_snake_case (answers are matched '
                f"that way). Fix: {bad}. Put the human wording in the question."
            )
        return self


class Condition(Strict):
    field: str
    op: Op
    value: Any = None

    @model_validator(mode="after")
    def _value_shape(self) -> Condition:
        if self.op in ("in", "not_in") and not isinstance(self.value, list):
            raise ValueError(f'op "{self.op}" needs a list value')
        if self.op in ("lt", "lte", "gt", "gte") and not isinstance(self.value, int | float):
            raise ValueError(f'op "{self.op}" needs a numeric value')
        if self.op != "exists" and self.value is None:
            raise ValueError(f'op "{self.op}" needs a value')
        return self


class DisqualifyRule(Strict):
    name: str
    when: list[Condition] = Field(min_length=1, description="All conditions must match (AND)")
    reason: str
    close_message: str | None = None


class ScoreRule(Strict):
    name: str
    when: list[Condition] = Field(min_length=1, description="All conditions must match (AND)")
    points: int


class QualificationConfig(Strict):
    required_fields: list[FieldSpec] = Field(min_length=1)
    disqualify_if: list[DisqualifyRule] = Field(default_factory=list)
    score_weights: list[ScoreRule] = Field(min_length=1)
    hot_lead_threshold: int = Field(gt=0)
    warm_lead_threshold: int = Field(default=40, ge=0)

    @property
    def field_keys(self) -> list[str]:
        return [f.key for f in self.required_fields]

    @model_validator(mode="after")
    def _consistency(self) -> QualificationConfig:
        keys = self.field_keys
        dupes = {k for k in keys if keys.count(k) > 1}
        if dupes:
            raise ValueError(f"duplicate required_fields keys: {sorted(dupes)}")
        if "zip" not in keys:
            raise ValueError('required_fields must include key "zip" (used for routing)')
        known = set(keys) | set(CONTACT_FIELDS)
        rules = [(r.name, r.when) for r in self.disqualify_if] + [
            (r.name, r.when) for r in self.score_weights
        ]
        for rule_name, conds in rules:
            for c in conds:
                if c.field not in known:
                    raise ValueError(
                        f'rule "{rule_name}" references unknown field "{c.field}". '
                        f"Known fields: {sorted(known)}"
                    )
        specs = {f.key: f for f in self.required_fields}
        for rule_name, conds in rules:
            for c in conds:
                spec = specs.get(c.field)
                if spec is None or c.op in ("exists", "lt", "lte", "gt", "gte"):
                    continue
                values = c.value if isinstance(c.value, list) else [c.value]
                if spec.type == "choice":
                    bad = [v for v in values if v not in spec.options]
                    if bad:
                        raise ValueError(
                            f'rule "{rule_name}" compares "{c.field}" to {bad}, which are not '
                            f"among its options {spec.options}"
                        )
                elif spec.type == "boolean" and any(not isinstance(v, bool) for v in values):
                    raise ValueError(
                        f'rule "{rule_name}" compares boolean field "{c.field}" to {values}. '
                        "Use true or false without quotes."
                    )
        if self.warm_lead_threshold >= self.hot_lead_threshold:
            raise ValueError("warm_lead_threshold must be below hot_lead_threshold")
        max_points = sum(r.points for r in self.score_weights if r.points > 0)
        if self.hot_lead_threshold > max_points:
            raise ValueError(
                f"hot_lead_threshold {self.hot_lead_threshold} exceeds the maximum "
                f"achievable score {max_points}"
            )
        return self


# --------------------------------------------------------------------- routing


class Rep(Strict):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str
    email: str
    phone: str | None = None
    slack_user_id: str | None = None
    calendar_id: str | None = None
    business_hours: BusinessHours


class Office(Strict):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str
    zips: list[str] = Field(min_length=1)
    reps: list[Rep] = Field(min_length=1)

    @field_validator("zips", mode="before")
    @classmethod
    def _zips(cls, v: Any) -> list[str]:
        if not isinstance(v, list):
            raise ValueError("must be a list")
        return expand_zips([str(x) for x in v])


class HotLeadBehavior(Strict):
    notify: Literal["immediate", "normal"] = "immediate"
    slack_mention: bool = True
    offer_earliest_slot: bool = True


class AppointmentConfig(Strict):
    kind: str = Field(min_length=1, description='e.g. "home consultation", "loan consultation"')
    duration_minutes: int = Field(gt=0)
    slots_to_offer: int = Field(default=3, gt=0)
    lookahead_days: int = Field(default=7, gt=0)
    minimum_notice_hours: int = Field(default=2, ge=0)
    confirmation_note: str | None = Field(
        default=None,
        description='Said word for word in the booking confirmation, e.g. "A Zoom meeting invite '
        'has been sent to your email."',
    )


class RoutingConfig(Strict):
    offices: list[Office] = Field(min_length=1)
    default_office: str | None = None
    assignment: Literal["round_robin"] = "round_robin"
    hot_lead: HotLeadBehavior = Field(default_factory=HotLeadBehavior)
    appointment: AppointmentConfig
    slack_channel: str

    @model_validator(mode="after")
    def _consistency(self) -> RoutingConfig:
        office_ids = [o.id for o in self.offices]
        if len(set(office_ids)) != len(office_ids):
            raise ValueError("duplicate office ids")
        rep_ids = [r.id for o in self.offices for r in o.reps]
        if len(set(rep_ids)) != len(rep_ids):
            raise ValueError("duplicate rep ids across offices")
        owner: dict[str, str] = {}
        for o in self.offices:
            for z in o.zips:
                if z in owner:
                    raise ValueError(f'zip {z} appears in offices "{owner[z]}" and "{o.id}"')
                owner[z] = o.id
        if self.default_office is not None and self.default_office not in office_ids:
            raise ValueError(f'default_office "{self.default_office}" is not a known office id')
        return self


# ----------------------------------------------------------------- crm mapping


class CRMMapping(Strict):
    crm: Literal["hubspot"]
    pipeline: str
    stage_on_create: str
    stage_on_booked: str
    field_map: dict[str, str] = Field(
        description="Internal field key -> CRM property name. Internal keys are the "
        "qualification field keys plus the core keys the engine writes."
    )

    @model_validator(mode="after")
    def _required(self) -> CRMMapping:
        for k in REQUIRED_CRM_FIELDS:
            if k not in self.field_map:
                raise ValueError(f'field_map must map "{k}"')
        return self


# ---------------------------------------------------------------------- bundle


class KnowledgeDoc(Strict):
    source: str  # path relative to the company folder, e.g. "knowledge/faq.md"
    text: str


class CompanyBundle(Strict):
    slug: str
    root: str
    company: CompanyConfig
    qualification: QualificationConfig
    routing: RoutingConfig
    crm_mapping: CRMMapping
    knowledge: list[KnowledgeDoc] = Field(min_length=1)

    @model_validator(mode="after")
    def _cross_checks(self) -> CompanyBundle:
        if not _SLUG.match(self.slug):
            raise ValueError(f'slug "{self.slug}" must be lowercase letters, digits, underscores')
        service = set(self.company.service_area_zips)
        covered: set[str] = set()
        for o in self.routing.offices:
            covered.update(o.zips)
            outside = [z for z in o.zips if z not in service]
            if outside:
                raise ValueError(
                    f'office "{o.id}" has zips outside company.service_area_zips: {outside[:5]}'
                )
        uncovered = sorted(service - covered)
        if uncovered and self.routing.default_office is None:
            raise ValueError(
                f"service_area_zips not covered by any office and no default_office set: "
                f"{uncovered[:5]}"
            )
        allowed = set(self.qualification.field_keys) | set(CORE_CRM_FIELDS)
        unknown = [k for k in self.crm_mapping.field_map if k not in allowed]
        if unknown:
            raise ValueError(f"crm_mapping.field_map has unknown internal keys: {unknown}")
        unmapped = [k for k in self.qualification.field_keys if k not in self.crm_mapping.field_map]
        if unmapped:
            raise ValueError(f"required_fields not mapped in crm_mapping.field_map: {unmapped}")
        return self
