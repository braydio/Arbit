"""Notification helpers for external services.

Currently supports sending simple messages to a Discord webhook. The helpers
are intentionally lightweight so that other modules can reuse them without
rewriting webhook logic.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from typing import Optional

from .config import settings
from .metrics.exporter import ERRORS_TOTAL


def fmt_usd(amount: float) -> str:
    """Return *amount* formatted as a USD string.

    Parameters
    ----------
    amount:
        Numeric dollar amount to format.

    Returns
    -------
    str
        Dollar amount with thousands separator and two decimals, prefixed
        by ``$``.
    """

    return f"${amount:,.2f}"


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
        log.info("notify_discord: webhook not configured; skipping")
        return

    # Ensure webhook uses wait=true so Discord returns a response body
    url = webhook
    try:
        from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

        pr = urlparse(webhook)
        if pr.netloc.endswith("discord.com") or pr.netloc.endswith("discordapp.com"):
            qs = dict(parse_qsl(pr.query, keep_blank_values=True))
            if "wait" not in qs:
                qs["wait"] = "true"
                pr = pr._replace(query=urlencode(qs))
                url = urlunparse(pr)
    except Exception:
        url = webhook

    payload = json.dumps({"content": message}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Content-Type": "application/json",
            "User-Agent": "arbit-cli/1.0 (+https://github.com/)",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=3):
            log.info("notify_discord: sent message (%d chars)", len(message or ""))
            return
    except Exception as e:
        detail = None
        try:  # include response body when available (e.g., HTTPError)
            detail = getattr(e, "read", lambda: b"")()  # type: ignore[attr-defined]
            if detail:
                detail = detail.decode("utf-8", errors="ignore")
        except Exception:
            detail = None
        if hasattr(e, "code"):
            code = getattr(e, "code")
            if int(code) == 403:
                log.error(
                    "notify_discord: 403 Forbidden. Check webhook is valid and has access. (%s)",
                    detail or e,
                )
            else:
                log.error("notify_discord: HTTP %s error: %s", code, detail or e)
        else:
            log.error("notify_discord: send failed: %s", e)
        try:
            ERRORS_TOTAL.labels(venue, "discord_send").inc()
        except Exception:
            pass
