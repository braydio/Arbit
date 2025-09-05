"""Tests for streaming utilities and WebSocket integration."""

from types import SimpleNamespace
import asyncio

import pytest

from arbit.engine import executor
from arbit.models import Triangle


class DummyWs:
    """Minimal websocket client stub."""

    def __init__(self, book: dict):
        self.book = book
        self.calls = 0

    async def watch_order_book(self, symbol: str, depth: int):  # pragma: no cover - trivial
        self.calls += 1
        return self.book


def test_orderbook_stream_uses_websocket(monkeypatch) -> None:
    """When a websocket client is available it is preferred over REST."""

    import sys

    sys.modules.pop("arbit.adapters.ccxt_adapter", None)
    sys.modules["arbit.config"] = SimpleNamespace(
        creds_for=lambda ex: ("k", "s"), settings=SimpleNamespace(alpaca_base_url="")
    )
    import arbit.adapters.ccxt_adapter as ccxt_mod

    fake_cls = SimpleNamespace(alpaca=lambda params: SimpleNamespace(id="alpaca"))
    monkeypatch.setattr(ccxt_mod, "ccxt", fake_cls)
    monkeypatch.setattr(ccxt_mod, "ccxtpro", None)
    adapter = ccxt_mod.CcxtAdapter("alpaca")
    ws = DummyWs({"bids": [], "asks": []})
    adapter.ex_ws = ws

    async def run():
        stream = adapter.orderbook_stream(["BTC/USDT"], depth=1)
        symbol, book = await anext(stream)
        assert symbol == "BTC/USDT"
        assert book == {"bids": [], "asks": []}
        assert ws.calls == 1

    asyncio.run(run())


def test_orderbook_stream_rest_fallback(monkeypatch) -> None:
    """REST polling is used when websocket support is missing."""

    import sys

    sys.modules.pop("arbit.adapters.ccxt_adapter", None)
    sys.modules["arbit.config"] = SimpleNamespace(
        creds_for=lambda ex: ("k", "s"), settings=SimpleNamespace(alpaca_base_url="")
    )
    import arbit.adapters.ccxt_adapter as ccxt_mod

    fake_cls = SimpleNamespace(alpaca=lambda params: SimpleNamespace(id="alpaca"))
    monkeypatch.setattr(ccxt_mod, "ccxt", fake_cls)
    monkeypatch.setattr(ccxt_mod, "ccxtpro", None)
    adapter = ccxt_mod.CcxtAdapter("alpaca")

    called: dict[str, int] = {"n": 0}

    def fake_fetch(symbol: str, depth: int):
        called["n"] += 1
        return {"bids": [], "asks": []}

    monkeypatch.setattr(adapter, "fetch_orderbook", fake_fetch)

    async def run():
        stream = adapter.orderbook_stream(["ETH/USDT"], depth=5, poll_interval=0)
        symbol, _ = await anext(stream)
        assert symbol == "ETH/USDT"
        assert called["n"] == 1

    asyncio.run(run())


class DummyAdapter:
    """Adapter stub providing an order book stream."""

    def __init__(self, updates: list[tuple[str, dict]]):
        self.updates = updates

    async def orderbook_stream(self, symbols, depth):  # pragma: no cover - trivial
        for u in self.updates:
            yield u


def test_stream_triangles(monkeypatch) -> None:
    """Executor streams attempt triangles as books update."""

    tri = Triangle("A/B", "B/C", "A/C")
    updates = [
        ("A/B", {"bids": [[1, 1]], "asks": [[1, 1]]}),
        ("B/C", {"bids": [[1, 1]], "asks": [[1, 1]]}),
        ("A/C", {"bids": [[1, 1]], "asks": [[1, 1]]}),
    ]

    adapter = DummyAdapter(updates)

    def fake_try(adapter, tri, books, threshold, skip_reasons):
        return {"tri": tri, "net_est": 0.0, "fills": [], "realized_usdt": 0.0}

    monkeypatch.setattr(executor, "try_triangle", fake_try)

    async def run():
        gen = executor.stream_triangles(adapter, [tri], 0.0, depth=1)
        out = await anext(gen)
        assert out[0] == tri
        assert out[1]["tri"] == tri

    asyncio.run(run())

