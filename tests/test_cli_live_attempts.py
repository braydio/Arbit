"""Tests covering live CLI attempt persistence edge cases."""

from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest

from arbit.cli import utils as cli_utils
from arbit.models import Triangle


@pytest.mark.asyncio
async def test_live_run_records_skip_attempt(monkeypatch, tmp_path):
    """Skipped attempts should persist metadata and top-of-book snapshots."""

    triangle = Triangle("A/B", "B/C", "A/C")
    db_path = tmp_path / "attempts.sqlite"

    books = {
        "A/B": {"bids": [(1.0, 5.0)], "asks": [(1.1, 5.0)]},
        "B/C": {"bids": [(2.0, 5.0)], "asks": [(2.1, 5.0)]},
        "A/C": {"bids": [(3.0, 5.0)], "asks": [(3.1, 5.0)]},
    }

    class DummyAdapter:
        """Adapter stub supplying deterministic order books for tests."""

        def name(self) -> str:
            return "dummy"

        @staticmethod
        def balances() -> dict[str, float]:
            return {}

        @staticmethod
        def load_markets() -> dict[str, dict[str, float]]:
            return {symbol: {"symbol": symbol} for symbol in books}

        @staticmethod
        def fetch_orderbook(symbol: str, depth: int = 1) -> dict:
            return books.get(symbol, {"bids": [], "asks": []})

    dummy_settings = SimpleNamespace(
        sqlite_path=str(db_path),
        dry_run=True,
        net_threshold_bps=0.0,
        notional_per_trade_usd=100.0,
        max_slippage_bps=5.0,
        discord_min_notify_interval_secs=0.0,
        discord_attempt_notify=False,
        discord_trade_notify=False,
        discord_heartbeat_secs=0.0,
        alpaca_map_usdt_to_usd=False,
    )

    monkeypatch.setattr(cli_utils, "settings", dummy_settings)
    monkeypatch.setattr(cli_utils, "_triangles_for", lambda _venue: [triangle])
    monkeypatch.setattr(cli_utils, "_build_adapter", lambda _venue, _settings: DummyAdapter())
    monkeypatch.setattr(cli_utils, "_log_balances", lambda *_a, **_k: None)
    monkeypatch.setattr(cli_utils, "notify_discord", lambda *_a, **_k: None)

    async def _fake_stream(*_args, **_kwargs):
        yield triangle, None, ["below_threshold", "stale_book"], 0.25

    monkeypatch.setattr(cli_utils, "stream_triangles", _fake_stream)

    await cli_utils._live_run_for_venue("demo")

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            """
            SELECT ok, skip_reasons, ab_bid, ab_ask, bc_bid, bc_ask, ac_bid, ac_ask
            FROM triangle_attempts
            """
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    ok, reasons, ab_bid, ab_ask, bc_bid, bc_ask, ac_bid, ac_ask = row
    assert ok == 0
    assert reasons == "below_threshold,stale_book"
    assert (ab_bid, ab_ask) == (1.0, 1.1)
    assert (bc_bid, bc_ask) == (2.0, 2.1)
    assert (ac_bid, ac_ask) == (3.0, 3.1)
