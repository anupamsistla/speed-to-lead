"""Slack incoming-webhook notifier."""

from __future__ import annotations

import httpx

from leadagent.models import Notification


class SlackNotifier:
    def __init__(self, webhook_url: str, client: httpx.Client | None = None):
        if not webhook_url:
            raise ValueError("SLACK_WEBHOOK_URL is required when NOTIFIER_ADAPTER=slack")
        self.webhook_url = webhook_url
        self.client = client or httpx.Client(timeout=10)

    def notify(self, notification: Notification) -> None:
        resp = self.client.post(self.webhook_url, json=notification.to_slack_payload())
        resp.raise_for_status()
