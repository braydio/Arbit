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
    monkeypatch.setattr(
        cli_utils, "_build_adapter", lambda _venue, _settings: DummyAdapter()
    )
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


@pytest.mark.asyncio
async def test_live_run_closes_adapter_and_db(monkeypatch):
    """Adapter close coroutine should be awaited and DB handle closed."""

    class DummyAdapter:
        """Adapter stub with async close for cleanup verification."""

        def __init__(self) -> None:
            self.close_calls = 0
            self.closed = False

        def name(self) -> str:
            return "dummy"

        @staticmethod
        def balances() -> dict[str, float]:
            return {}

        @staticmethod
        def load_markets() -> dict[str, dict[str, float]]:
            return {}

        async def close(self) -> None:
            self.close_calls += 1
            self.closed = True

    class DummyConn:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    dummy_adapter = DummyAdapter()
    dummy_conn = DummyConn()

    dummy_settings = SimpleNamespace(
        sqlite_path=":memory:",
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
    monkeypatch.setattr(cli_utils, "_triangles_for", lambda _venue: [])
    monkeypatch.setattr(
        cli_utils, "_build_adapter", lambda _venue, _settings: dummy_adapter
    )
    monkeypatch.setattr(cli_utils, "_log_balances", lambda *_a, **_k: None)
    monkeypatch.setattr(cli_utils, "notify_discord", lambda *_a, **_k: None)
    monkeypatch.setattr(
        cli_utils, "_discover_triangles_from_markets", lambda *_a, **_k: []
    )
    monkeypatch.setattr(cli_utils, "init_db", lambda _path: dummy_conn)

    await cli_utils._live_run_for_venue("demo")

    assert dummy_conn.closed is True
    assert dummy_adapter.closed is True
    assert dummy_adapter.close_calls == 1


@pytest.mark.asyncio
async def test_live_run_defaults_to_suggestions_when_config_missing(monkeypatch):
    """Auto-discovered suggestions should seed sessions without config."""

    suggestions = [
        ["SOL/USDT", "SOL/BTC", "BTC/USDT"],
        ["ADA/USDT", "ADA/BTC", "BTC/USDT"],
    ]

    class DummyAdapter:
        """Adapter stub lacking fallback markets to force auto-suggestions."""

        def name(self) -> str:
            return "dummy"

        @staticmethod
        def balances() -> dict[str, float]:
            return {}

        @staticmethod
        def load_markets() -> dict[str, dict[str, float]]:
            return {}

    class DummyConn:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    dummy_adapter = DummyAdapter()
    dummy_conn = DummyConn()
    captured: dict[str, list[Triangle]] = {}

    dummy_settings = SimpleNamespace(
        sqlite_path=":memory:",
        dry_run=True,
        net_threshold_bps=0.0,
        notional_per_trade_usd=100.0,
        max_slippage_bps=5.0,
        discord_min_notify_interval_secs=0.0,
        discord_attempt_notify=False,
        discord_trade_notify=False,
        discord_heartbeat_secs=0.0,
        alpaca_map_usdt_to_usd=False,
        triangles_by_venue={},
    )

    monkeypatch.setattr(cli_utils, "settings", dummy_settings)
    monkeypatch.setattr(
        cli_utils, "_build_adapter", lambda _venue, _settings: dummy_adapter
    )
    monkeypatch.setattr(cli_utils, "_log_balances", lambda *_a, **_k: None)
    monkeypatch.setattr(cli_utils, "notify_discord", lambda *_a, **_k: None)
    monkeypatch.setattr(
        cli_utils,
        "_discover_triangles_from_markets",
        lambda *_a, **_k: suggestions,
    )
    monkeypatch.setattr(cli_utils, "init_db", lambda _path: dummy_conn)
    monkeypatch.setattr(cli_utils, "insert_triangle", lambda *_a, **_k: None)

    async def _fake_stream(adapter, tris, *_args, **_kwargs):
        captured["triangles"] = tris
        if False:  # pragma: no cover - ensures function is async generator
            yield None

    monkeypatch.setattr(cli_utils, "stream_triangles", _fake_stream)

    await cli_utils._live_run_for_venue("demo")

    assert dummy_conn.closed is True
    assert captured["triangles"]
    assert [(tri.leg_ab, tri.leg_bc, tri.leg_ac) for tri in captured["triangles"]] == [
        tuple(row) for row in suggestions
    ]
