"""CLI command tests for the arbitrage app."""

from __future__ import annotations

import logging
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

sys.modules["arbit.adapters.ccxt_adapter"] = types.SimpleNamespace(CCXTAdapter=object)

from arbit import cli  # noqa: E402


class DummyAdapter:
    """Minimal adapter for testing CLI commands."""

    def __init__(self) -> None:
        self.books_calls: list[str] = []
        self.balance_calls = 0

    def fetch_orderbook(self, symbol: str, depth: int = 10) -> dict:
        self.books_calls.append(symbol)
        books = {
            "ETH/USDT": {"asks": [(2000.0, 1.0)], "bids": []},
            "ETH/BTC": {"bids": [(0.05, 1.0)], "asks": []},
            "BTC/USDT": {"bids": [(60000.0, 1.0)], "asks": []},
        }
        return books.get(symbol, {"bids": [], "asks": []})

    def balances(self) -> dict[str, float]:
        self.balance_calls += 1
        return {"USDT": 100.0}

    @staticmethod
    def create_order(*args, **kwargs):  # pragma: no cover - not used
        """Stubbed order creation used solely for interface compatibility."""
        return None

    @staticmethod
    def cancel_order(*args, **kwargs):  # pragma: no cover - not used
        """Stubbed order cancellation used solely for interface compatibility."""
        return None

    @staticmethod
    def fetch_balance(*args, **kwargs) -> float:  # pragma: no cover
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

        @staticmethod
        def sleep(_secs: float) -> None:
            """Advance the fake clock without real delay."""
            return None

    monkeypatch.setattr(cli, "time", _Time())

    adapter = DummyAdapter()
    monkeypatch.setattr(cli, "_build_adapter", lambda venue, _settings: adapter)

    runner = CliRunner()
    result = runner.invoke(cli.app, ["fitness", "--secs", "1"])
    assert result.exit_code == 0
    assert adapter.balance_calls == 1


def test_fitness_simulate(monkeypatch):
    monkeypatch.setenv("ARBIT_API_KEY", "x")
    monkeypatch.setenv("ARBIT_API_SECRET", "y")

    class _Time:
        def __init__(self):
            self.t = 0.0

        def time(self) -> float:
            self.t += 1.0
            return self.t

        @staticmethod
        def sleep(_secs: float) -> None:
            return None

    monkeypatch.setattr(cli, "time", _Time())

    class DummySimAdapter:
        """Adapter with minimal behavior to satisfy try_triangle in simulate mode."""

        def __init__(self) -> None:
            # Fixed profitable top-of-book across legs
            self._books = {
                "ETH/USDT": {"asks": [(2000.0, 1.0)], "bids": [(1999.5, 1.0)]},
                "ETH/BTC": {"bids": [(0.05, 1.0)], "asks": [(0.049, 1.0)]},
                "BTC/USDT": {"bids": [(41000.0, 1.0)], "asks": [(41010.0, 1.0)]},
            }
            self.balance_calls = 0

        def fetch_orderbook(self, symbol: str, depth: int = 10) -> dict:
            ob = self._books.get(symbol)
            return ob if ob else {"bids": [], "asks": []}

        @staticmethod
        def fetch_fees(_symbol: str) -> tuple[float, float]:
            return 0.0, 0.001  # maker, taker

        @staticmethod
        def min_notional(_symbol: str) -> float:
            return 1.0

        def create_order(self, spec):  # type: ignore[no-untyped-def]
            # Synthesize a taker fill at top-of-book
            ob = self.fetch_orderbook(spec.symbol, 1)
            price = ob["asks"][0][0] if spec.side == "buy" else ob["bids"][0][0]
            fee = self.fetch_fees(spec.symbol)[1] * price * spec.qty
            return {
                "id": "dryrun",
                "symbol": spec.symbol,
                "side": spec.side,
                "qty": spec.qty,
                "price": price,
                "fee": fee,
            }

        def balances(self) -> dict[str, float]:
            self.balance_calls += 1
            return {"USDT": 500.0}

    adapter = DummySimAdapter()
    monkeypatch.setattr(cli, "_build_adapter", lambda venue, _settings: adapter)

    runner = CliRunner()
    result = runner.invoke(cli.app, ["fitness", "--secs", "1", "--simulate"])
    assert result.exit_code == 0


def test_fitness_debug_log(monkeypatch, caplog):
    """`--debug-log` should emit debug messages."""

    monkeypatch.setenv("ARBIT_API_KEY", "x")
    monkeypatch.setenv("ARBIT_API_SECRET", "y")

    class _Time:
        def __init__(self):
            self.t = 0.0

        def time(self) -> float:
            self.t += 1.0
            return self.t

        @staticmethod
        def sleep(_secs: float) -> None:
            return None

    monkeypatch.setattr(cli, "time", _Time())

    adapter = DummyAdapter()
    monkeypatch.setattr(cli, "_build_adapter", lambda venue, _settings: adapter)

    runner = CliRunner()
    with caplog.at_level(logging.DEBUG):
        result = runner.invoke(cli.app, ["fitness", "--secs", "1", "--debug-log"])
    assert result.exit_code == 0
    assert any("detailed logging enabled" in m for m in caplog.messages)


def test_keys_check(monkeypatch):
    class DummyCcxt:
        """Minimal ccxt-like exchange for testing `keys_check`."""

        @staticmethod
        def load_markets() -> dict:
            """Return available markets for the dummy exchange."""
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


def test_usage_without_args() -> None:
    """Invoking CLI without arguments should display usage information."""
    runner = CliRunner()
    result = runner.invoke(cli.app, [])
    assert result.exit_code == 0
    assert "Usage" in result.output


def test_usage_with_bad_command() -> None:
    """An unknown command should produce a usage message."""
    runner = CliRunner()
    result = runner.invoke(cli.app, ["bogus"])
    assert result.exit_code != 0
    assert "Usage" in result.output


def test_live() -> None:
    pytest.skip("live command runs indefinitely")


def test_help_lists_commands() -> None:
    """Global `--help` should list available commands with summaries."""

    runner = CliRunner()
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    assert result.output.count("keys:check") == 1
    assert result.output.count("fitness") == 1
    assert result.output.count("live") == 1
    assert result.output.count("markets:limits") == 1
    assert result.output.count("config:recommend") == 1


def test_help_verbose_shows_details() -> None:
    """`--help-verbose` should include flags and sample output."""

    runner = CliRunner()
    result = runner.invoke(cli.app, ["--help-verbose"])
    assert result.exit_code == 0
    assert "Command reference" in result.output
    assert "--secs" in result.output
    assert "Sample output" in result.output


def test_markets_limits(monkeypatch):
    class DummyCcxt:
        @staticmethod
        def load_markets() -> dict:
            return {"ETH/USDT": {}, "BTC/USDT": {}}

    class DummyAdapter:
        def __init__(self) -> None:
            self.ex = DummyCcxt()

        @staticmethod
        def fetch_fees(symbol: str) -> tuple[float, float]:
            return (0.001, 0.001) if symbol else (0.0, 0.0)

        @staticmethod
        def min_notional(symbol: str) -> float:
            return 5.0 if symbol else 0.0

    monkeypatch.setattr(cli, "_build_adapter", lambda venue, _settings: DummyAdapter())
    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        ["markets:limits", "--venue", "alpaca", "--symbols", "ETH/USDT,BTC/USDT"],
    )
    assert result.exit_code == 0


def test_config_recommend(monkeypatch):
    class DummyAdapter:
        class _EX:
            @staticmethod
            def load_markets():
                return {"ETH/USDT": {}, "ETH/BTC": {}, "BTC/USDT": {}}

        def __init__(self) -> None:
            self.ex = self._EX()

        @staticmethod
        def fetch_fees(_s: str) -> tuple[float, float]:
            return (0.001, 0.001)

        @staticmethod
        def min_notional(_s: str) -> float:
            return 5.0

        @staticmethod
        def fetch_orderbook(_s: str, _d: int = 1) -> dict:
            return {"asks": [(2000.0, 1.0)], "bids": [(1999.0, 1.0)]}

    monkeypatch.setattr(cli, "_build_adapter", lambda venue, _settings: DummyAdapter())
    runner = CliRunner()
    result = runner.invoke(cli.app, ["config:recommend", "--venue", "alpaca"])
    assert result.exit_code == 0
