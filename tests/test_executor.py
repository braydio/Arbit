"""Tests for executor utility functions."""

import sys
import types

# ruff: noqa: E402

sys.modules["arbit.config"] = types.SimpleNamespace(
    settings=types.SimpleNamespace(
        notional_per_trade_usd=200.0,
        net_threshold_bps=10.0,
        dry_run=True,
        prom_port=9109,
        log_level="INFO",
        reserve_amount_usd=0.0,
        reserve_percent=0.0,
    )
)

from arbit import try_triangle
from arbit.adapters.base import ExchangeAdapter, OrderSpec
from arbit.models import Triangle


class DummyAdapter(ExchangeAdapter):
    """Lightweight adapter stub used for executor tests."""

    def __init__(self, books, balance: float = 1000.0):
        self.books = books
        self.balance = balance
        self.orders: list[OrderSpec] = []

    def name(self) -> str:  # pragma: no cover - not used
        return "dummy"

    def fetch_orderbook(self, symbol: str, depth: int = 10):
        return self.books.get(symbol, {"bids": [], "asks": []})

    def fetch_fees(self, symbol: str):  # pragma: no cover - simple stub
        return (0.0, 0.0)

    def min_notional(self, symbol: str) -> float:  # pragma: no cover - simple stub
        return 0.0

    def load_markets(
        self,
    ) -> dict[str, dict[str, float]]:  # pragma: no cover - simple stub
        return {s: {"symbol": s} for s in self.books.keys()}

    def create_order(self, spec: OrderSpec):
        book = self.books[spec.symbol]
        price = book["asks"][0][0] if spec.side == "buy" else book["bids"][0][0]
        self.orders.append(spec)
        return {"price": price, "qty": spec.qty, "fee": 0.0}

    def balances(self):  # pragma: no cover - not used
        return {}

    def fetch_balance(self, asset: str) -> float:  # pragma: no cover - simple stub
        return self.balance


def profitable_books() -> dict[str, dict[str, list[tuple[float, float]]]]:
    """Return a set of books that yields a profitable cycle."""
    return {
        "ETH/USDT": {"asks": [(100.0, 10.0)], "bids": [(99.0, 10.0)]},
        "ETH/BTC": {"bids": [(0.1, 10.0)], "asks": [(0.2, 10.0)]},
        "BTC/USDT": {"bids": [(1100.0, 10.0)], "asks": [(1101.0, 10.0)]},
    }


def unprofitable_books() -> dict[str, dict[str, list[tuple[float, float]]]]:
    """Return books adjusted to make the cycle unprofitable."""
    data = profitable_books()
    data["BTC/USDT"] = {"bids": [(900.0, 10.0)], "asks": [(901.0, 10.0)]}
    return data


def test_try_triangle_executes_on_profit() -> None:
    """Arbitrage cycle executes when net edge exceeds threshold."""
    tri = Triangle("ETH/USDT", "ETH/BTC", "BTC/USDT")
    books = profitable_books()
    adapter = DummyAdapter(books)
    thresh = sys.modules["arbit.config"].settings.net_threshold_bps / 10000.0
    res = try_triangle(adapter, tri, books, thresh)
    assert res is not None
    assert len(adapter.orders) == 3


def test_try_triangle_skips_when_unprofitable() -> None:
    """Cycle is skipped when estimated net edge is below threshold."""
    tri = Triangle("ETH/USDT", "ETH/BTC", "BTC/USDT")
    books = unprofitable_books()
    adapter = DummyAdapter(books)
    thresh = sys.modules["arbit.config"].settings.net_threshold_bps / 10000.0
    res = try_triangle(adapter, tri, books, thresh)
    assert res is None
    assert len(adapter.orders) == 0


def test_try_triangle_respects_reserve(monkeypatch) -> None:
    """Cycle is skipped when reserve leaves no available balance."""
    tri = Triangle("ETH/USDT", "ETH/BTC", "BTC/USDT")
    books = profitable_books()
    adapter = DummyAdapter(books, balance=40.0)
    cfg = sys.modules["arbit.config"].settings
    monkeypatch.setattr(cfg, "reserve_amount_usd", 50.0)
    monkeypatch.setattr(sys.modules["arbit.engine.executor"], "settings", cfg)
    thresh = cfg.net_threshold_bps / 10000.0
    skips: list[str] = []
    res = try_triangle(adapter, tri, books, thresh, skips)
    assert res is None
    assert "reserve" in skips
