"""Tests for the CCXT exchange adapter implementation."""

import pytest

ccxt = pytest.importorskip("ccxt")

from arbit.adapters import CCXTAdapter, ExchangeAdapter
from arbit.adapters.base import OrderSpec as LegacyOrderSpec
from arbit.config import settings
from arbit.models import OrderSpec


def test_initialization() -> None:
    """Adapter initialization returns a configured client."""
    adapter = CCXTAdapter("alpaca", "k", "s")
    assert isinstance(adapter, ExchangeAdapter)
    assert adapter.client.id == "alpaca"


def test_fetch_order_book(monkeypatch) -> None:
    """Order books are retrieved via the underlying ccxt client."""
    adapter = CCXTAdapter("kraken", "k", "s")

    def fake_fetch_order_book(symbol: str, *args, **kwargs) -> dict:
        assert symbol == "BTC/USD"
        return {"bids": [], "asks": []}

    monkeypatch.setattr(adapter.client, "fetch_order_book", fake_fetch_order_book)
    order_book = adapter.fetch_order_book("BTC/USD")
    assert order_book == {"bids": [], "asks": []}


def test_create_order(monkeypatch) -> None:
    """Order creation passes through to the ccxt client."""
    adapter = CCXTAdapter("alpaca", "k", "s")
    monkeypatch.setattr(settings, "dry_run", False)

    def fake_create_order(symbol, order_type, side, amount, price):
        return {
            "id": "1",
            "price": price,
            "amount": amount,
            "fees": [{"cost": 0.1}],
        }

    monkeypatch.setattr(adapter.client, "create_order", fake_create_order)
    order = OrderSpec(symbol="ETH/USDT", side="buy", quantity=1.0, price=1000.0)
    fill = adapter.create_order(order)
    assert fill.order_id == "1"
    assert fill.quantity == 1.0
    assert fill.fee == 0.1
    assert fill["qty"] == 1.0


def test_create_order_accepts_legacy_spec(monkeypatch) -> None:
    """Legacy OrderSpec dataclasses remain supported."""
    adapter = CCXTAdapter("alpaca", "k", "s")
    monkeypatch.setattr(settings, "dry_run", False)

    def fake_create_order(symbol, order_type, side, amount, price):
        assert amount == 1.0
        assert price is None
        return {
            "id": "1",
            "price": 1000.0,
            "amount": amount,
            "fees": [{"cost": 0.1}],
        }

    monkeypatch.setattr(adapter.client, "create_order", fake_create_order)
    order = LegacyOrderSpec(symbol="ETH/USDT", side="buy", qty=1.0)
    fill = adapter.create_order(order)
    assert fill["qty"] == 1.0
    assert fill["price"] == 1000.0
    assert fill["fee"] == 0.1


def test_cancel_order(monkeypatch) -> None:
    """Cancellation requests are forwarded to the client."""
    adapter = CCXTAdapter("alpaca", "k", "s")
    called: dict[str, str] = {}

    def fake_cancel_order(order_id: str, symbol: str) -> None:
        called["order_id"] = order_id
        called["symbol"] = symbol

    monkeypatch.setattr(adapter.client, "cancel_order", fake_cancel_order)
    adapter.cancel_order("1", "ETH/USDT")
    assert called == {"order_id": "1", "symbol": "ETH/USDT"}


def test_fetch_balance(monkeypatch) -> None:
    """Balance retrieval uses the underlying client API."""
    adapter = CCXTAdapter("kraken", "k", "s")

    def fake_fetch_balance() -> dict:
        return {"free": {"USD": 10.0}}

    monkeypatch.setattr(adapter.client, "fetch_balance", fake_fetch_balance)
    balance = adapter.fetch_balance("USD")
    assert balance == 10.0
