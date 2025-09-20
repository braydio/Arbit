"""Tests for executor utility functions."""

import sys
import types

# ruff: noqa: E402

import logging


sys.modules["arbit.config"] = types.SimpleNamespace(
    settings=types.SimpleNamespace(
        notional_per_trade_usd=200.0,
        net_threshold_bps=10.0,
        dry_run=True,
        prom_port=9109,
        log_level="INFO",
        reserve_amount_usd=0.0,
        reserve_percent=0.0,
    ),
    creds_for=lambda _ex: (None, None),
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


def books_missing_opposite_sides() -> dict[str, dict[str, list[tuple[float, float]]]]:
    """Return books where sell legs lack asks but still have bids."""

    return {
        "ETH/USDT": {"asks": [(100.0, 10.0)], "bids": [(99.0, 10.0)]},
        "ETH/BTC": {"bids": [(0.1, 10.0)], "asks": []},
        "BTC/USDT": {"bids": [(1100.0, 10.0)], "asks": []},
    }


def books_missing_required_side() -> dict[str, dict[str, list[tuple[float, float]]]]:
    """Return books where a required bid side is absent."""

    return {
        "ETH/USDT": {"asks": [(100.0, 10.0)], "bids": [(99.0, 10.0)]},
        "ETH/BTC": {"asks": [(0.2, 10.0)], "bids": []},
        "BTC/USDT": {"bids": [(1100.0, 10.0)], "asks": [(1101.0, 10.0)]},
    }


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
    skip_meta: dict[str, object] = {}
    res = try_triangle(adapter, tri, books, thresh, skip_meta=skip_meta)
    assert res is None
    assert len(adapter.orders) == 0
    assert "net_est" in skip_meta and isinstance(skip_meta["net_est"], float)
    assert skip_meta["net_est"] < thresh
    assert skip_meta.get("prices") == {
        "ab_ask": 100.0,
        "bc_bid": 0.1,
        "ac_bid": 900.0,
    }


def test_try_triangle_logs_skip_details(caplog) -> None:
    """Debug logging captures pricing context when a cycle is skipped."""

    tri = Triangle("ETH/USDT", "ETH/BTC", "BTC/USDT")
    books = unprofitable_books()
    adapter = DummyAdapter(books)
    thresh = sys.modules["arbit.config"].settings.net_threshold_bps / 10000.0
    skips: list[str] = []
    with caplog.at_level(logging.DEBUG, logger="arbit.engine.executor"):
        res = try_triangle(adapter, tri, books, thresh, skips)
    assert res is None
    assert skips == ["below_threshold"]
    executor_records = [
        rec
        for rec in caplog.records
        if rec.name == "arbit.engine.executor" and "try_triangle skip" in rec.message
    ]
    assert executor_records, "expected try_triangle skip debug log"
    msg = executor_records[-1].message
    assert "below_threshold" in msg
    assert "ab_ask" in msg and "bc_bid" in msg and "ac_bid" in msg


def test_try_triangle_executes_without_opposite_sides() -> None:
    """Executor ignores missing asks on sell legs when bids are present."""

    tri = Triangle("ETH/USDT", "ETH/BTC", "BTC/USDT")
    books = books_missing_opposite_sides()
    adapter = DummyAdapter(books)
    thresh = sys.modules["arbit.config"].settings.net_threshold_bps / 10000.0
    result = try_triangle(adapter, tri, books, thresh)
    assert result is not None
    assert len(adapter.orders) == 3


def test_try_triangle_skips_when_required_side_missing() -> None:
    """Executor skips when necessary bids are absent on a sell leg."""

    tri = Triangle("ETH/USDT", "ETH/BTC", "BTC/USDT")
    books = books_missing_required_side()
    adapter = DummyAdapter(books)
    thresh = sys.modules["arbit.config"].settings.net_threshold_bps / 10000.0
    skips: list[str] = []
    result = try_triangle(adapter, tri, books, thresh, skips)
    assert result is None
    assert "incomplete_book" in skips
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


def test_try_triangle_honours_ccxt_fee_overrides(monkeypatch) -> None:
    """CCXT taker overrides should flip net estimation above the threshold."""

    monkeypatch.setitem(sys.modules, "ccxt", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "ccxt.pro", types.SimpleNamespace())
    from arbit.adapters import ccxt_adapter as ccxta
    from arbit.engine import executor as exec_mod

    books = {
        "ETH/USDT": {"asks": [(100.0, 5.0)], "bids": [(99.95, 5.0)]},
        "ETH/BTC": {"asks": [(0.02055, 5.0)], "bids": [(0.02045, 5.0)]},
        "BTC/USDT": {"asks": [(4905.0, 5.0)], "bids": [(4900.0, 5.0)]},
    }

    class DummyClient:
        id = "kraken"
        fees = {"trading": {"maker": 0.001, "taker": 0.001}}

        def market(self, symbol: str):
            return {"symbol": symbol, "maker": 0.001, "taker": 0.001}

    class MockCCXTAdapter(ccxta.CCXTAdapter):
        """CCXT adapter stub exposing real ``fetch_fees`` behaviour."""

        def __init__(self, books_data):
            self.ex = DummyClient()
            self.client = self.ex
            self.ex_ws = None
            self._fee = {}
            self.books = books_data
            self.orders: list[OrderSpec] = []

        def fetch_orderbook(self, symbol: str, depth: int = 10):  # noqa: D401
            """Return the in-memory order book for *symbol*."""

            return self.books[symbol]

        def min_notional(self, symbol: str) -> float:
            return 0.0

        def create_order(self, spec: OrderSpec):
            book = self.books[spec.symbol]
            price = book["asks"][0][0] if spec.side == "buy" else book["bids"][0][0]
            self.orders.append(spec)
            return {"price": price, "qty": spec.qty, "fee": 0.0}

        def balances(self):  # pragma: no cover - not needed for this test
            return {}

        def fetch_balance(self, asset: str) -> float:
            return 10_000.0

    tri = Triangle("ETH/USDT", "ETH/BTC", "BTC/USDT")

    base_settings = types.SimpleNamespace(
        notional_per_trade_usd=200.0,
        net_threshold_bps=5.0,
        dry_run=True,
        reserve_amount_usd=0.0,
        reserve_percent=0.0,
        max_slippage_bps=0.0,
        fee_overrides={},
    )
    monkeypatch.setattr(ccxta, "settings", base_settings, raising=False)
    monkeypatch.setattr(exec_mod, "settings", base_settings, raising=False)

    adapter = MockCCXTAdapter(books)
    threshold = base_settings.net_threshold_bps / 10000.0
    skips: list[str] = []
    result = try_triangle(adapter, tri, books, threshold, skips)
    assert result is None
    assert "below_threshold" in skips

    override_settings = types.SimpleNamespace(
        notional_per_trade_usd=200.0,
        net_threshold_bps=5.0,
        dry_run=True,
        reserve_amount_usd=0.0,
        reserve_percent=0.0,
        max_slippage_bps=0.0,
        fee_overrides={
            "kraken": {
                "ETH/USDT": {"maker": 0.0, "taker": 0.0},
                "ETH/BTC": {"maker": 0.0, "taker": 0.0},
                "BTC/USDT": {"maker": 0.0, "taker": 0.0},
            }
        },
    )
    monkeypatch.setattr(ccxta, "settings", override_settings, raising=False)
    monkeypatch.setattr(exec_mod, "settings", override_settings, raising=False)

    adapter_override = MockCCXTAdapter(books)
    threshold_override = override_settings.net_threshold_bps / 10000.0
    result_override = try_triangle(adapter_override, tri, books, threshold_override, [])
    assert result_override is not None
    assert len(adapter_override.orders) == 3
    assert adapter_override.fetch_fees("ETH/USDT")[1] == 0.0
