"""CLI command tests for the arbitrage app."""

from __future__ import annotations

import sys
import types

import pytest

from typer.testing import CliRunner

sys.modules["arbit.config"] = types.SimpleNamespace(
    settings=types.SimpleNamespace(
        log_level="INFO",
        prom_port=9109,
        dry_run=True,
        net_threshold_bps=10.0,
        notional_per_trade_usd=200.0,
        exchanges=["alpaca"],
    )
)

sys.modules["arbit.adapters.ccxt_adapter"] = types.SimpleNamespace(CcxtAdapter=object)

from arbit import cli  # noqa: E402


class DummyAdapter:
    """Minimal adapter for testing CLI commands."""

    def __init__(self) -> None:
        self.books_calls: list[str] = []

    def fetch_orderbook(self, symbol: str, depth: int = 10) -> dict:
        self.books_calls.append(symbol)
        books = {
            "ETH/USDT": {"asks": [(2000.0, 1.0)], "bids": []},
            "BTC/ETH": {"bids": [(0.05, 1.0)], "asks": []},
            "BTC/USDT": {"bids": [(60000.0, 1.0)], "asks": []},
        }
        return books.get(symbol, {"bids": [], "asks": []})

    def create_order(self, *args, **kwargs):  # pragma: no cover - not used
        pass

    def cancel_order(self, *args, **kwargs):  # pragma: no cover - not used
        pass

    def fetch_balance(self, *args, **kwargs) -> float:  # pragma: no cover
        return 0.0


def test_fitness(monkeypatch):
    monkeypatch.setenv("ARBIT_API_KEY", "x")
    monkeypatch.setenv("ARBIT_API_SECRET", "y")

    class _Time:
        def __init__(self):
            self.t = 0.0

        def time(self) -> float:
            self.t += 1.0
            return self.t

        def sleep(self, _secs: float) -> None:
            pass

    monkeypatch.setattr(cli, "time", _Time())

    adapter = DummyAdapter()
    monkeypatch.setattr(cli, "_build_adapter", lambda venue, _settings: adapter)

    runner = CliRunner()
    result = runner.invoke(cli.app, ["fitness", "--secs", "1"])
    assert result.exit_code == 0


def test_keys_check(monkeypatch):
    class DummyCcxt:
        def load_markets(self):
            return {"BTC/USD": {}}

    class DummyKeyAdapter(DummyAdapter):
        def __init__(self):
            super().__init__()
            self.ex = DummyCcxt()

    adapter = DummyKeyAdapter()
    monkeypatch.setattr(cli, "_build_adapter", lambda venue, _settings: adapter)

    runner = CliRunner()
    result = runner.invoke(cli.app, ["keys_check"])
    assert result.exit_code == 0
    assert adapter.books_calls == ["BTC/USD"]


def test_live() -> None:
    pytest.skip("live command runs indefinitely")
