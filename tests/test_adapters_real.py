"""HubSpot and Slack adapters against faked HTTP. Not verified against the live APIs."""

from __future__ import annotations

import json

import httpx
import pytest

from leadagent.adapters import build_adapters
from leadagent.adapters.hubspot import BASE_URL, HubSpotCRM, HubSpotError
from leadagent.adapters.mock import MockCalendar, MockChannel, MockCRM, MockNotifier
from leadagent.adapters.slack import SlackNotifier
from leadagent.adapters.stubs import GoogleCalendar, TwilioChannel
from leadagent.models import Notification


class FakeHubSpot:
    def __init__(self):
        self.contacts: dict[str, dict] = {}
        self.deals: dict[str, dict] = {}
        self.assoc: dict[str, list[str]] = {}
        self.requests: list[tuple[str, str]] = []
        self.seq = 100

    def _id(self):
        self.seq += 1
        return str(self.seq)

    def __call__(self, req: httpx.Request) -> httpx.Response:
        path, method = req.url.path, req.method
        self.requests.append((method, path))
        body = json.loads(req.content) if req.content else {}
        assert req.headers["authorization"] == "Bearer tok"
        if path == "/crm/v3/objects/contacts/search":
            hits = []
            for cid, c in self.contacts.items():
                for g in body["filterGroups"]:
                    f = g["filters"][0]
                    if c["properties"].get(f["propertyName"]) == f["value"]:
                        hits.append({"id": cid, **c})
                        break
            return httpx.Response(200, json={"results": hits[:1]})
        if path == "/crm/v3/objects/contacts" and method == "POST":
            cid = self._id()
            self.contacts[cid] = {"properties": body["properties"]}
            return httpx.Response(201, json={"id": cid, **self.contacts[cid]})
        if path.startswith("/crm/v3/objects/contacts/") and method == "PATCH":
            cid = path.rsplit("/", 1)[1]
            self.contacts[cid]["properties"].update(body["properties"])
            return httpx.Response(200, json={"id": cid, **self.contacts[cid]})
        if path == "/crm/v3/pipelines/deals":
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": "pipe1",
                            "label": "Residential Sales",
                            "stages": [
                                {"id": "s_new", "label": "New Lead"},
                                {"id": "s_book", "label": "Consultation Booked"},
                            ],
                        }
                    ]
                },
            )
        if "/associations/deals" in path:
            cid = path.split("/")[5]
            return httpx.Response(
                200, json={"results": [{"toObjectId": d} for d in self.assoc.get(cid, [])]}
            )
        if path == "/crm/v3/objects/deals" and method == "POST":
            did = self._id()
            self.deals[did] = {"properties": body["properties"]}
            return httpx.Response(201, json={"id": did})
        if path.startswith("/crm/v3/objects/deals/"):
            did = path.rsplit("/", 1)[1]
            if method == "PATCH":
                self.deals[did]["properties"].update(body["properties"])
            return httpx.Response(200, json={"id": did, **self.deals[did]})
        if "/associations/default/contacts/" in path and method == "PUT":
            parts = path.split("/")
            self.assoc.setdefault(parts[-1], []).append(parts[5])
            return httpx.Response(200, json={})
        return httpx.Response(404, text=f"unhandled {method} {path}")


@pytest.fixture
def hubspot(bundle):
    fake = FakeHubSpot()
    client = httpx.Client(
        base_url=BASE_URL,
        headers={"Authorization": "Bearer tok"},
        transport=httpx.MockTransport(fake),
    )
    crm = HubSpotCRM(
        "tok", mapped_properties=list(bundle.crm_mapping.field_map.values()), client=client
    )
    return crm, fake


def test_hubspot_creates_contact_and_deal_then_moves_stage(hubspot):
    crm, fake = hubspot
    c = crm.upsert_contact(
        name="Jamie Rivera",
        phone="+13035550142",
        email=None,
        properties={"homeowner_status": "owner", "lead_score": 90},
        pipeline="Residential Sales",
        stage="New Lead",
    )
    props = fake.contacts[c.id]["properties"]
    assert props["firstname"] == "Jamie" and props["lastname"] == "Rivera"
    assert props["homeowner_status"] == "owner" and props["lead_score"] == "90"
    [deal] = fake.deals.values()
    assert deal["properties"]["dealstage"] == "s_new" and deal["properties"]["pipeline"] == "pipe1"

    crm.update_stage(c.id, pipeline="Residential Sales", stage="Consultation Booked")
    assert len(fake.deals) == 1  # moved, not duplicated
    assert next(iter(fake.deals.values()))["properties"]["dealstage"] == "s_book"


def test_hubspot_finds_existing_and_maps_back(hubspot):
    crm, fake = hubspot
    crm.upsert_contact(
        name="Jamie",
        phone="+13035550142",
        email=None,
        properties={"roof_type": "tile"},
        pipeline="Residential Sales",
        stage="New Lead",
    )
    found = crm.find_contact(phone="+13035550142", email="nobody@x.co")
    assert found and found.properties == {"roof_type": "tile"} and found.stage == "s_new"
    again = crm.upsert_contact(
        name=None,
        phone="+13035550142",
        email=None,
        properties={"roof_type": "metal"},
        pipeline="Residential Sales",
        stage="New Lead",
    )
    assert again.id == found.id and len(fake.contacts) == 1
    assert crm.find_contact(phone="+19995550000", email=None) is None


def test_hubspot_unknown_stage_is_a_clear_error(hubspot):
    crm, _ = hubspot
    with pytest.raises(HubSpotError, match="Nope"):
        crm.upsert_contact(
            name="A",
            phone="1",
            email=None,
            properties={},
            pipeline="Residential Sales",
            stage="Nope",
        )


def test_hubspot_http_error_surfaces():
    client = httpx.Client(
        base_url=BASE_URL,
        transport=httpx.MockTransport(lambda r: httpx.Response(401, text="bad token")),
    )
    with pytest.raises(HubSpotError, match="401"):
        HubSpotCRM("tok", client=client).find_contact(phone=None, email="a@b.co")


def test_hubspot_requires_token():
    with pytest.raises(ValueError, match="HUBSPOT_TOKEN"):
        HubSpotCRM("")


def test_slack_posts_payload(clock):
    seen = {}

    def handler(req):
        seen["url"], seen["json"] = str(req.url), json.loads(req.content)
        return httpx.Response(200, text="ok")

    n = SlackNotifier(
        "https://hooks.example/abc", httpx.Client(transport=httpx.MockTransport(handler))
    )
    n.notify(
        Notification(
            kind="hot_lead",
            channel="#c",
            title="Hot lead: Jamie",
            fields={"Score": "90/100"},
            mention="U12345678",
            priority="urgent",
            lead_id="l",
            created_at=clock.now(),
            note="call now",
        )
    )
    assert seen["url"] == "https://hooks.example/abc"
    assert "<@U12345678>" in seen["json"]["text"] and "Hot lead: Jamie" in seen["json"]["text"]
    assert "*Score:* 90/100" in seen["json"]["blocks"][1]["text"]["text"]


def test_slack_non_id_mention_is_plain(clock):
    p = Notification(
        kind="new_lead",
        channel="#c",
        title="T",
        mention="Maya Ortiz",
        lead_id="l",
        created_at=clock.now(),
    ).to_slack_payload()
    assert p["text"].startswith("@Maya Ortiz ")


def test_slack_error_raises(clock):
    n = SlackNotifier(
        "https://h", httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    )
    with pytest.raises(httpx.HTTPStatusError):
        n.notify(
            Notification(
                kind="new_lead", channel="#c", title="T", lead_id="l", created_at=clock.now()
            )
        )


def test_slack_requires_url():
    with pytest.raises(ValueError, match="SLACK_WEBHOOK_URL"):
        SlackNotifier("")


def test_factory_defaults_to_mocks(bundle, clock):
    a = build_adapters(bundle, clock, env={})
    assert isinstance(a.channel, MockChannel) and isinstance(a.crm, MockCRM)
    assert isinstance(a.calendar, MockCalendar) and isinstance(a.notifier, MockNotifier)


def test_factory_real_adapters_from_env(bundle, clock):
    a = build_adapters(
        bundle,
        clock,
        env={
            "CRM_ADAPTER": "hubspot",
            "HUBSPOT_TOKEN": "t",
            "NOTIFIER_ADAPTER": "slack",
            "SLACK_WEBHOOK_URL": "https://h",
            "CHANNEL_ADAPTER": "twilio",
            "CALENDAR_ADAPTER": "google",
        },
    )
    assert isinstance(a.crm, HubSpotCRM) and isinstance(a.notifier, SlackNotifier)
    assert isinstance(a.channel, TwilioChannel) and isinstance(a.calendar, GoogleCalendar)


def test_factory_rejects_bad_values_and_missing_credentials(bundle, clock):
    with pytest.raises(ValueError, match="CRM_ADAPTER"):
        build_adapters(bundle, clock, env={"CRM_ADAPTER": "salesforce"})
    with pytest.raises(ValueError, match="HUBSPOT_TOKEN"):
        build_adapters(bundle, clock, env={"CRM_ADAPTER": "hubspot"})


def test_stubs_fail_loudly(clock):
    with pytest.raises(NotImplementedError):
        TwilioChannel().send(None, "x")  # type: ignore[arg-type]
    with pytest.raises(NotImplementedError):
        GoogleCalendar().is_free("r", clock.now(), 60)
