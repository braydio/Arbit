"""Ensure Alpaca live CLI avoids ccxt usage."""

import sys
from types import SimpleNamespace

from typer.testing import CliRunner


def test_live_alpaca_uses_native_adapter(monkeypatch):
    """Running ``live`` for Alpaca should not touch ccxt."""

    class DummyCCXT(SimpleNamespace):
        def __getattr__(self, name):  # pragma: no cover - fail on access
            raise AssertionError("ccxt should not be accessed")

    # Ensure importing CLI doesn't pull real ccxt
    monkeypatch.setitem(sys.modules, "ccxt", DummyCCXT())
    sys.modules.pop("arbit.cli", None)
    import arbit.cli as cli

    # Replace adapters and heavy helpers with light stubs
    class DummyAlpaca:
        def name(self):
            return "alpaca"

        def load_markets(self):
            return {"A/B": {}, "B/C": {}, "A/C": {}}

        def balances(self):  # pragma: no cover - trivial
            return {}

    def fail_ccxt(*_a, **_kw):  # pragma: no cover - fail if used
        raise AssertionError("CCXTAdapter should not be used")

    monkeypatch.setattr(cli, "AlpacaAdapter", DummyAlpaca)
    monkeypatch.setattr(cli, "CCXTAdapter", fail_ccxt)
    dummy_settings = SimpleNamespace(
        dry_run=True,
        sqlite_path=":memory:",
        prom_port=0,
        net_threshold_bps=0.0,
        notional_per_trade_usd=0.0,
        max_slippage_bps=0.0,
        discord_min_notify_interval_secs=0.0,
        discord_attempt_notify=False,
        discord_live_stop_notify=False,
        alpaca_map_usdt_to_usd=False,
    )
    monkeypatch.setattr(cli, "settings", dummy_settings)
    monkeypatch.setattr(
        cli, "_triangles_for", lambda _v: [cli.Triangle("A/B", "B/C", "A/C")]
    )
    monkeypatch.setattr(cli, "init_db", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "insert_triangle", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "insert_attempt", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "insert_fill", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "notify_discord", lambda *_a, **_k: None)
    monkeypatch.setattr(cli, "start_metrics_server", lambda *_a, **_k: None)
    monkeypatch.setattr(
        cli,
        "CYCLE_LATENCY",
        SimpleNamespace(
            labels=lambda *_a, **_k: SimpleNamespace(observe=lambda *_a, **_k: None)
        ),
    )
    monkeypatch.setattr(
        cli,
        "ORDERS_TOTAL",
        SimpleNamespace(
            labels=lambda *_a, **_k: SimpleNamespace(inc=lambda *_a, **_k: None)
        ),
    )
    monkeypatch.setattr(
        cli,
        "PROFIT_TOTAL",
        SimpleNamespace(
            labels=lambda *_a, **_k: SimpleNamespace(set=lambda *_a, **_k: None)
        ),
    )
    monkeypatch.setattr(
        cli,
        "FILLS_TOTAL",
        SimpleNamespace(
            labels=lambda *_a, **_k: SimpleNamespace(inc=lambda *_a, **_k: None)
        ),
    )

    async def fake_stream(adapter, tris, threshold):
        yield (
            tris[0],
            {"net_est": 0.0, "fills": [], "realized_usdt": 0.0},
            [],
            0.0,
            {},
        )

    monkeypatch.setattr(cli, "stream_triangles", fake_stream)

    runner = CliRunner()
    res = runner.invoke(cli.app, ["live", "--venue", "alpaca"])
    assert res.exit_code == 0, res.output
