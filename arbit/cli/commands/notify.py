"""Notification utility CLI commands."""

from __future__ import annotations

from arbit.config import settings
from arbit.notify import notify_discord

from ..core import app, log


@app.command("notify:test")
@app.command("notify_test")
def notify_test(message: str = "[notify] test message from arbit.cli") -> None:
    """Send a test message to the configured Discord webhook."""

    if not getattr(settings, "discord_webhook_url", None):
        log.error("notify:test no webhook configured (set DISCORD_WEBHOOK_URL)")
        return
    try:
        notify_discord("notify", message)
    except Exception as exc:  # defensive; notify_discord already swallows errors
        log.error("notify:test error: %s", exc)


__all__ = ["notify_test"]
