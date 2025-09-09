"""Notification helpers for external services.

Currently supports sending simple messages to a Discord webhook. The helpers
are intentionally lightweight so that other modules can reuse them without
rewriting webhook logic.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Optional

from .config import settings
from .metrics.exporter import ERRORS_TOTAL


def notify_discord(venue: str, message: str, url: Optional[str] = None) -> None:
    """Send *message* to a Discord webhook.

    Parameters
    ----------
    venue:
        Name of the venue or subsystem issuing the notification. Used for
        labeling error metrics.
    message:
        Text content to send to Discord.
    url:
        Optional override for the webhook URL. Defaults to
        ``settings.discord_webhook_url``.

    Notes
    -----
    Any network or configuration errors are swallowed so that notification
    failures never interrupt trading flows. When an error occurs, the
    ``errors_total`` metric is incremented with stage ``discord_send``.
    """

    webhook = url or getattr(settings, "discord_webhook_url", None)
    if not webhook:
        return

    data = json.dumps({"content": message}).encode("utf-8")
    req = urllib.request.Request(
        webhook, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=3):
            return
    except Exception:
        try:
            ERRORS_TOTAL.labels(venue, "discord_send").inc()
        except Exception:
            pass
