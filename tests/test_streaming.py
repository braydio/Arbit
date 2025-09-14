"""Tests for streaming utilities and WebSocket integration."""

import asyncio
from builtins import anext
from types import SimpleNamespace

from arbit.engine import executor
from arbit.models import Triangle

from tests.alpaca_mocks import MockDataStream, MockHistClient, MockTradingClient


def test_orderbook_stream_reconnects(monkeypatch) -> None:
    """Alpaca stream yields multiple symbols and survives disconnects."""

    import arbit.adapters.alpaca_adapter as aa

    monkeypatch.setattr(aa, "TradingClient", MockTradingClient)
    monkeypatch.setattr(aa, "CryptoHistoricalDataClient", MockHistClient)
    monkeypatch.setattr(aa, "CryptoDataStream", MockDataStream)
    monkeypatch.setattr(
        aa,
        "settings",
        SimpleNamespace(alpaca_base_url="", alpaca_map_usdt_to_usd=False),
    )
    monkeypatch.setattr(aa, "creds_for", lambda ex: ("k", "s"))

    # two runs emitting different symbols before stopping
    from types import SimpleNamespace as SN

    MockDataStream.updates_runs = [
        [SN(symbol="BTC/USD", bids=[], asks=[])],
        [SN(symbol="ETH/USD", bids=[], asks=[])],
    ]
    adapter = aa.AlpacaAdapter()

    async def run():
        gen = adapter.orderbook_stream(
            ["BTC/USD", "ETH/USD"], depth=1, reconnect_delay=0
        )
        sym1, _ = await anext(gen)
        sym2, _ = await anext(gen)
        await gen.aclose()
        assert {sym1, sym2} == {"BTC/USD", "ETH/USD"}
        assert len(MockDataStream.instances) >= 2

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
