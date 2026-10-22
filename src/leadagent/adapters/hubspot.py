"""HubSpot CRM adapter (private app token, free developer account).

Contacts hold the mapped properties from crm_mapping.yaml. A deal in the configured pipeline
tracks the stage (stage_on_create, then stage_on_booked), associated to the contact.
Pipeline and stage labels from config are resolved to HubSpot ids at first use.
"""

from __future__ import annotations

from typing import Any

import httpx

from leadagent.models import CRMContact

BASE_URL = "https://api.hubapi.com"
STANDARD_PROPS = ["email", "phone", "firstname", "lastname"]


class HubSpotError(RuntimeError):
    pass


class HubSpotCRM:
    def __init__(
        self,
        token: str,
        *,
        mapped_properties: list[str] | None = None,
        client: httpx.Client | None = None,
    ):
        if not token:
            raise ValueError("HUBSPOT_TOKEN is required when CRM_ADAPTER=hubspot")
        self.mapped_properties = mapped_properties or []
        self.client = client or httpx.Client(
            base_url=BASE_URL, headers={"Authorization": f"Bearer {token}"}, timeout=15
        )
        self._pipelines: dict[str, Any] | None = None

    # ------------------------------------------------------------------ http
    def _req(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        resp = self.client.request(method, path, **kwargs)
        if resp.status_code >= 400:
            raise HubSpotError(f"HubSpot {method} {path} failed: {resp.status_code} {resp.text}")
        return resp.json() if resp.content else {}

    def _to_contact(
        self, obj: dict[str, Any], pipeline: str | None, stage: str | None
    ) -> CRMContact:
        p = obj.get("properties", {})
        name = " ".join(x for x in (p.get("firstname"), p.get("lastname")) if x) or None
        extras = {k: v for k, v in p.items() if k in self.mapped_properties and v not in (None, "")}
        return CRMContact(
            id=str(obj["id"]),
            name=name,
            phone=p.get("phone"),
            email=p.get("email"),
            properties=extras,
            pipeline=pipeline,
            stage=stage,
        )

    # --------------------------------------------------------------- contacts
    def find_contact(self, *, phone: str | None, email: str | None) -> CRMContact | None:
        groups = []
        if email:
            groups.append(
                {"filters": [{"propertyName": "email", "operator": "EQ", "value": email}]}
            )
        if phone:
            groups.append(
                {"filters": [{"propertyName": "phone", "operator": "EQ", "value": phone}]}
            )
        if not groups:
            return None
        data = self._req(
            "POST",
            "/crm/v3/objects/contacts/search",
            json={
                "filterGroups": groups,  # groups are OR'd
                "properties": STANDARD_PROPS + self.mapped_properties,
                "limit": 1,
            },
        )
        results = data.get("results", [])
        if not results:
            return None
        contact = self._to_contact(results[0], None, None)
        contact.pipeline, contact.stage = self._deal_state(contact.id)
        return contact

    @staticmethod
    def _split_name(name: str | None) -> dict[str, str]:
        if not name:
            return {}
        first, _, last = name.strip().partition(" ")
        return {"firstname": first, **({"lastname": last} if last else {})}

    def upsert_contact(
        self,
        *,
        name: str | None,
        phone: str | None,
        email: str | None,
        properties: dict[str, Any],
        pipeline: str,
        stage: str,
    ) -> CRMContact:
        props: dict[str, Any] = {k: str(v) for k, v in properties.items() if v is not None}
        props.update(self._split_name(name))
        if phone:
            props["phone"] = phone
        if email:
            props["email"] = email
        existing = self.find_contact(phone=phone, email=email)
        if existing:
            obj = self._req(
                "PATCH", f"/crm/v3/objects/contacts/{existing.id}", json={"properties": props}
            )
            contact_id = existing.id
        else:
            obj = self._req("POST", "/crm/v3/objects/contacts", json={"properties": props})
            contact_id = str(obj["id"])
        self.update_stage(
            contact_id, pipeline=pipeline, stage=stage, deal_name=name or email or phone
        )
        contact = self._to_contact(obj, pipeline, stage)
        contact.id = contact_id
        return contact

    # ------------------------------------------------------------------ deals
    def _pipeline_ids(self, pipeline: str, stage: str) -> tuple[str, str]:
        if self._pipelines is None:
            data = self._req("GET", "/crm/v3/pipelines/deals")
            self._pipelines = {p["label"].lower(): p for p in data.get("results", [])}
            self._pipelines.update({p["id"]: p for p in data.get("results", [])})
        p = self._pipelines.get(pipeline.lower()) or self._pipelines.get(pipeline)
        if p is None:
            raise HubSpotError(f"HubSpot deal pipeline '{pipeline}' not found")
        for s in p.get("stages", []):
            if s["label"].lower() == stage.lower() or s["id"] == stage:
                return p["id"], s["id"]
        raise HubSpotError(f"stage '{stage}' not found in HubSpot pipeline '{pipeline}'")

    def _deal_for(self, contact_id: str) -> dict[str, Any] | None:
        assoc = self._req("GET", f"/crm/v4/objects/contacts/{contact_id}/associations/deals")
        results = assoc.get("results", [])
        if not results:
            return None
        deal_id = results[0]["toObjectId"]
        return self._req(
            "GET", f"/crm/v3/objects/deals/{deal_id}", params={"properties": "dealstage,pipeline"}
        )

    def _deal_state(self, contact_id: str) -> tuple[str | None, str | None]:
        deal = self._deal_for(contact_id)
        if not deal:
            return None, None
        p = deal.get("properties", {})
        return p.get("pipeline"), p.get("dealstage")

    def update_stage(
        self, contact_id: str, *, pipeline: str, stage: str, deal_name: str | None = None
    ) -> None:
        pipeline_id, stage_id = self._pipeline_ids(pipeline, stage)
        deal = self._deal_for(contact_id)
        if deal:
            self._req(
                "PATCH",
                f"/crm/v3/objects/deals/{deal['id']}",
                json={"properties": {"pipeline": pipeline_id, "dealstage": stage_id}},
            )
            return
        created = self._req(
            "POST",
            "/crm/v3/objects/deals",
            json={
                "properties": {
                    "dealname": f"Inbound lead: {deal_name or contact_id}",
                    "pipeline": pipeline_id,
                    "dealstage": stage_id,
                }
            },
        )
        self._req(
            "PUT",
            f"/crm/v4/objects/deals/{created['id']}/associations/default/contacts/{contact_id}",
        )
