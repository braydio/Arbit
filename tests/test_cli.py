from __future__ import annotations

from typer.testing import CliRunner

from arbit import cli
from arbit.metrics import exporter


class DummyAdapter:
    """Minimal adapter for testing CLI commands."""

    def __init__(self) -> None:
        self.books_calls: list[str] = []

    def fetch_order_book(self, symbol: str) -> dict:
        self.books_calls.append(symbol)
        books = {
            "ETH/USDT": {"asks": [(2000.0, 1.0)]},
            "BTC/ETH": {"bids": [(0.05, 1.0)]},
            "BTC/USDT": {"bids": [(60000.0, 1.0)]},
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
    monkeypatch.setattr(cli, "time", type("T", (), {"sleep": lambda self, _: None})())

    adapter = DummyAdapter()
    monkeypatch.setattr(cli, "_build_adapter", lambda venue, settings: adapter)

    runner = CliRunner()
    result = runner.invoke(cli.app, ["fitness", "--secs", "1"])
    assert result.exit_code == 0
    assert "net=" in result.stdout
    assert adapter.books_calls == ["ETH/USDT", "BTC/ETH", "BTC/USDT"]


def test_live(monkeypatch):
    monkeypatch.setenv("ARBIT_API_KEY", "x")
    monkeypatch.setenv("ARBIT_API_SECRET", "y")
    monkeypatch.setattr(cli, "time", type("T", (), {"sleep": lambda self, _: None})())

    adapter = DummyAdapter()
    monkeypatch.setattr(cli, "_build_adapter", lambda venue, settings: adapter)

    init_called = {}
    monkeypatch.setattr(cli, "init_db", lambda path: init_called.setdefault("called", True))
    insert_called = {}
    monkeypatch.setattr(cli, "insert_triangle", lambda conn, tri: insert_called.setdefault("called", True))
    monkeypatch.setattr(cli, "start_metrics_server", lambda port: None)
    monkeypatch.setattr(cli, "try_triangle", lambda *args, **kwargs: True)

    runner = CliRunner()
    result = runner.invoke(cli.app, ["live", "--cycles", "1"])
    assert result.exit_code == 0
    assert init_called.get("called")
    assert insert_called.get("called")
    exporter.ORDERS_TOTAL._value._v = 0
