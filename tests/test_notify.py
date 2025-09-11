from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from arbit import notify


def test_notify_discord_noop_when_url_missing(monkeypatch):
    """notify_discord should return quietly when no webhook is configured."""
    monkeypatch.setattr(notify, "settings", SimpleNamespace(discord_webhook_url=None))
    with patch("urllib.request.urlopen") as mock_open:
        notify.notify_discord("test", "hello")
    assert mock_open.call_count == 0


def test_notify_discord_sends_with_url(monkeypatch):
    """notify_discord should attempt a network call when URL is set."""
    monkeypatch.setattr(
        notify,
        "settings",
        SimpleNamespace(discord_webhook_url="https://example.com"),
    )
    with patch("urllib.request.urlopen") as mock_open:
        notify.notify_discord("test", "hi")
        assert mock_open.call_count == 1
        req = mock_open.call_args.args[0]
        assert req.full_url == "https://example.com"


def test_fmt_usd_formats_with_separator():
    """fmt_usd should include separators and dollar sign."""
    assert notify.fmt_usd(1234.5) == "$1,234.50"
