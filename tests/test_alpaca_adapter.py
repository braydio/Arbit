"""Unit tests for AlpacaAdapter REST helpers."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from arbit.adapters.base import OrderSpec
from tests.alpaca_mocks import MockHistClient, MockTradingClient


def _setup(monkeypatch):
    """Reload adapter module with mocked clients."""
    import arbit.adapters.alpaca_adapter as aa

    monkeypatch.setattr(aa, "TradingClient", MockTradingClient)
    monkeypatch.setattr(aa, "CryptoHistoricalDataClient", MockHistClient)
    monkeypatch.setattr(aa, "CryptoDataStream", object)
    monkeypatch.setattr(
        aa,
        "settings",
        SimpleNamespace(
            alpaca_base_url="",
            alpaca_map_usdt_to_usd=False,
            dry_run=False,
        ),
    )
    monkeypatch.setattr(aa, "creds_for", lambda ex: ("k", "s"))
    return aa


def test_create_order_calls_submit(monkeypatch) -> None:
    aa = _setup(monkeypatch)

    # stub enum classes and request type
    class OrderSide:
        BUY = "buy"
        SELL = "sell"

    class TimeInForce:
        IOC = "IOC"

    class MarketOrderRequest:
        def __init__(self, symbol, qty, side, time_in_force):
            self.symbol = symbol
            self.qty = qty
            self.side = side
            self.time_in_force = time_in_force

    monkeypatch.setattr(aa, "OrderSide", OrderSide)
    monkeypatch.setattr(aa, "TimeInForce", TimeInForce)
    monkeypatch.setattr(aa, "MarketOrderRequest", MarketOrderRequest)

    adapter = aa.AlpacaAdapter()
    spec = OrderSpec(symbol="BTC/USD", side="buy", qty=1)
    res = adapter.create_order(spec)
    tc = adapter.trading  # type: ignore[attr-defined]
    assert tc.submitted_orders[0].symbol == "BTC/USD"
    assert res["symbol"] == "BTC/USD" and res["qty"] == 1


def test_balances_and_fetch_balance(monkeypatch) -> None:
    aa = _setup(monkeypatch)
    adapter = aa.AlpacaAdapter()
    tc = adapter.trading  # type: ignore[attr-defined]
    bals = adapter.balances()
    assert tc.positions_called == 1 and tc.account_called == 1
    assert bals["BTCUSD"] == 0.5 and bals["USD"] == 100.0
    bal = adapter.fetch_balance("BTCUSD")
    assert bal == 0.5
    assert tc.positions_called == 2 and tc.account_called == 2


def test_close_stops_active_stream(monkeypatch) -> None:
    """The ``close`` helper should stop and clear the active stream."""

    aa = _setup(monkeypatch)
    adapter = aa.AlpacaAdapter()

    class StopSignal:
        """Simple stub tracking whether ``stop`` was invoked."""

        def __init__(self) -> None:
            self.stopped = False

        def stop(self) -> None:
            self.stopped = True

    stream = StopSignal()
    adapter._stream = stream  # type: ignore[attr-defined]

    asyncio.run(adapter.close())

    assert stream.stopped
    assert adapter._stream is None  # type: ignore[attr-defined]
