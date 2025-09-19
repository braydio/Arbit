"""CLI command tests for the arbitrage app."""

from __future__ import annotations

import asyncio
import json
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
        discord_live_stop_notify=False,
    )
)

from arbit import cli  # noqa: E402
from arbit.cli.commands import config as config_cmds  # noqa: E402
from arbit.cli.commands import live as live_cmd  # noqa: E402


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

        def load_markets(self) -> dict:
            return self.ex.load_markets()

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


def test_live_single_venue(monkeypatch):
    """`live` should default to the single venue when `--venues` is absent."""

    calls: list[tuple[str, dict]] = []

    async def _fake_run(venue_name: str, **kwargs) -> None:
        calls.append((venue_name, kwargs))

    monkeypatch.setattr(live_cmd, "_live_run_for_venue", _fake_run)
    monkeypatch.setattr(live_cmd, "start_metrics_server", lambda *_: None)

    runner = CliRunner()
    result = runner.invoke(cli.app, ["live", "--venue", "kraken"])

    assert result.exit_code == 0
    assert calls == [
        (
            "kraken",
            {
                "symbols": None,
                "auto_suggest_top": 0,
                "attempt_notify_override": None,
            },
        )
    ]


def test_live_multi_venues(monkeypatch):
    """`live` should fan out to multiple venues when `--venues` is provided."""

    calls: list[tuple[str, dict]] = []

    async def _fake_run(venue_name: str, **kwargs) -> None:
        await asyncio.sleep(0)
        calls.append((venue_name, kwargs))

    monkeypatch.setattr(live_cmd, "_live_run_for_venue", _fake_run)
    monkeypatch.setattr(live_cmd, "start_metrics_server", lambda *_: None)

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "live",
            "--venue",
            "alpaca",
            "--venues",
            "kraken,alpaca,kraken",
            "--symbols",
            "ETH/USDT,BTC/USDT",
            "--auto-suggest-top",
            "3",
        ],
    )

    assert result.exit_code == 0
    assert {venue for venue, _ in calls} == {"alpaca", "kraken"}
    assert all(
        call[1]
        == {
            "symbols": "ETH/USDT,BTC/USDT",
            "auto_suggest_top": 3,
            "attempt_notify_override": None,
        }
        for call in calls
    )
    assert len(calls) == 2


def test_live_help_mentions_venues() -> None:
    """`live --help` should document the `--venues` flag and omit the legacy command."""

    runner = CliRunner()
    result = runner.invoke(cli.app, ["live", "--help"])

    assert result.exit_code == 0
    assert "--venues" in result.output
    assert "live:multi" not in result.output


def test_config_discover_writes_env(monkeypatch, tmp_path) -> None:
    """`config:discover` should persist triangles to the requested env file."""

    env_file = tmp_path / ".env"
    existing = {"alpaca": [["ETH/USDC", "ETH/BTC", "BTC/USDC"]]}
    env_file.write_text(
        "# header\nFOO=1\n" + f"TRIANGLES_BY_VENUE={json.dumps(existing)}\n",
        encoding="utf-8",
    )

    class _Adapter:
        @staticmethod
        def load_markets() -> dict:
            return {}

    monkeypatch.setattr(
        config_cmds, "_build_adapter", lambda _venue, _settings: _Adapter()
    )
    monkeypatch.setattr(
        config_cmds,
        "_discover_triangles_from_markets",
        lambda _markets: [("ETH/USDT", "ETH/BTC", "BTC/USDT")],
    )

    runner = CliRunner()
    result = runner.invoke(
        cli.app,
        [
            "config:discover",
            "--venue",
            "kraken",
            "--write-env",
            "--env-path",
            str(env_file),
        ],
    )
    assert result.exit_code == 0, result.stdout

    contents = env_file.read_text(encoding="utf-8")
    assert "FOO=1" in contents
    assert "# header" in contents.splitlines()[0]
    comment = "# Auto-generated by `python -m arbit.cli config:discover`"
    assert contents.count(comment) == 1
    payload_line = next(
        line for line in contents.splitlines() if line.startswith("TRIANGLES_BY_VENUE=")
    )
    payload = json.loads(payload_line.split("=", 1)[1])
    assert payload["alpaca"] == existing["alpaca"]
    assert payload["kraken"] == [["ETH/USDT", "ETH/BTC", "BTC/USDT"]]


def test_live() -> None:
    pytest.skip("live command runs indefinitely")


def test_help_lists_commands() -> None:
    """Global `--help` should list available commands with summaries."""

    runner = CliRunner()
    result = runner.invoke(cli.app, ["--help"])
    assert result.exit_code == 0
    assert result.output.count("keys:check") == 1
    assert result.output.count("fitness") == 1
    assert result.output.count("live") >= 1
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


def test_command_help_verbose_filters_sections() -> None:
    """`COMMAND --help-verbose` should show only that command's verbose help."""

    runner = CliRunner()
    result = runner.invoke(cli.app, ["fitness", "--help-verbose"])
    assert result.exit_code == 0
    assert "Monitor bid/ask spreads" in result.output
    assert "--venues" not in result.output

    live_result = runner.invoke(cli.app, ["live", "--help-verbose"])
    assert live_result.exit_code == 0
    assert "--venues" in live_result.output
    assert "markets:limits" not in live_result.output


def test_live_command_accepts_single_venue(monkeypatch) -> None:
    """`live` should run a single venue loop when only `--venue` is provided."""

    calls: list[str] = []

    async def _fake_live(venue: str, **_: object) -> None:
        calls.append(venue)

    monkeypatch.setattr(cli, "_live_run_for_venue", _fake_live)
    monkeypatch.setattr(cli, "start_metrics_server", lambda *_a, **_k: None)

    runner = CliRunner()
    result = runner.invoke(cli.app, ["live", "--venue", "alpaca"])
    assert result.exit_code == 0
    assert calls == ["alpaca"]


def test_live_command_runs_multiple_venues(monkeypatch) -> None:
    """`live --venues` should fan out concurrent loops for each venue supplied."""

    calls: list[str] = []

    async def _fake_live(venue: str, **_: object) -> None:
        calls.append(venue)

    monkeypatch.setattr(cli, "_live_run_for_venue", _fake_live)
    monkeypatch.setattr(cli, "start_metrics_server", lambda *_a, **_k: None)

    runner = CliRunner()
    result = runner.invoke(cli.app, ["live", "--venues", "alpaca,kraken"])
    assert result.exit_code == 0
    assert set(calls) == {"alpaca", "kraken"}


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


def test_live_uses_alpaca_adapter(monkeypatch) -> None:
    """`live` path should instantiate `AlpacaAdapter` and avoid CCXT calls."""

    dummy_settings = types.SimpleNamespace(
        sqlite_path=":memory:",
        alpaca_map_usdt_to_usd=False,
        dry_run=True,
    )
    monkeypatch.setattr(cli, "settings", dummy_settings)
    monkeypatch.setattr(
        cli, "init_db", lambda _p: types.SimpleNamespace(close=lambda: None)
    )
    monkeypatch.setattr(cli, "notify_discord", lambda *a, **k: None)

    calls = {"alpaca": 0}

    class DummyAlpaca:
        def __init__(self) -> None:
            calls["alpaca"] += 1

        @staticmethod
        def name() -> str:
            return "alpaca"

        @staticmethod
        def balances() -> dict[str, float]:
            return {}

        @staticmethod
        def load_markets() -> dict[str, dict[str, float]]:
            return {}

        @staticmethod
        async def close() -> None:  # pragma: no cover - trivial
            return None

    monkeypatch.setattr(cli, "AlpacaAdapter", DummyAlpaca)

    def _fail(*_a, **_k) -> None:  # pragma: no cover - defensive
        raise AssertionError("CCXTAdapter should not be used for alpaca")

    monkeypatch.setattr(cli, "CCXTAdapter", _fail)

    asyncio.run(cli._live_run_for_venue("alpaca"))
    assert calls["alpaca"] == 1
