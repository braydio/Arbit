"""Tests for executor utility functions."""

import sys
import types

sys.modules["arbit.config"] = types.SimpleNamespace(
    settings=types.SimpleNamespace(
        notional_per_trade_usd=200.0,
        net_threshold_bps=10.0,
        dry_run=True,
        prom_port=9109,
        log_level="INFO",
    )
)

from arbit.engine.executor import try_tri
from arbit.engine.triangle import Triangle
from arbit.adapters.base import ExchangeAdapter, OrderSpec


class DummyAdapter(ExchangeAdapter):
    def __init__(self, books):
        self.books = books
        self.orders: list[OrderSpec] = []

    def name(self) -> str:  # pragma: no cover - not used
        return "dummy"

    def fetch_orderbook(self, symbol: str, depth: int = 10):
        return self.books.get(symbol, {"bids": [], "asks": []})

    def fetch_fees(self, symbol: str):  # pragma: no cover - simple stub
        return (0.0, 0.0)

    def min_notional(self, symbol: str) -> float:  # pragma: no cover - simple stub
        return 0.0

    def create_order(self, spec: OrderSpec):
        book = self.books[spec.symbol]
        price = book["asks"][0][0] if spec.side == "buy" else book["bids"][0][0]
        self.orders.append(spec)
        return {"price": price, "qty": spec.qty, "fee": 0.0}

    def balances(self):  # pragma: no cover - not used
        return {}


def profitable_books() -> dict[str, dict[str, list[tuple[float, float]]]]:
    return {
        "ETH/USDT": {"asks": [(100.0, 10.0)], "bids": [(99.0, 10.0)]},
        "BTC/ETH": {"bids": [(0.1, 10.0)], "asks": [(0.2, 10.0)]},
        "BTC/USDT": {"bids": [(1100.0, 10.0)], "asks": [(1101.0, 10.0)]},
    }


def unprofitable_books() -> dict[str, dict[str, list[tuple[float, float]]]]:
    data = profitable_books()
    data["BTC/USDT"] = {"bids": [(900.0, 10.0)], "asks": [(901.0, 10.0)]}
    return data


def test_try_tri_executes_on_profit() -> None:
    tri = Triangle("ETH/USDT", "BTC/ETH", "BTC/USDT")
    adapter = DummyAdapter(profitable_books())
    res = try_tri(adapter, tri)
    assert res is not None
    assert len(adapter.orders) == 3


def test_try_tri_skips_when_unprofitable() -> None:
    tri = Triangle("ETH/USDT", "BTC/ETH", "BTC/USDT")
    adapter = DummyAdapter(unprofitable_books())
    res = try_tri(adapter, tri)
    assert res is None
    assert len(adapter.orders) == 0

