"""Tests for the AlpacaAdapter order book streaming."""

import asyncio
import importlib
import sys
from builtins import anext
from types import SimpleNamespace


class DummyTradingClient:
    """Minimal trading client stub used by the adapter."""

    def __init__(self, *args, **kwargs) -> None:
        pass


class DummyHistClient:
    """Minimal historical data client stub used by the adapter."""

    def __init__(self, *args, **kwargs) -> None:
        pass


class FakeStream:
    """Websocket stream that emits one update then stops."""

    instances: list["FakeStream"] = []

    def __init__(self, key: str, secret: str) -> None:
        self.handler = None
        FakeStream.instances.append(self)

    def subscribe_orderbooks(self, handler, *symbols) -> None:
        self.handler = handler
        self.symbols = symbols

    async def _run_forever(self) -> None:  # pragma: no cover - trivial
        await self.handler(SimpleNamespace(symbol="BTC/USD", bids=[], asks=[]))
        return

    def stop(self) -> None:  # pragma: no cover - trivial
        pass


def test_orderbook_stream_reconnect(monkeypatch) -> None:
    """The stream should reconnect and map USD pairs back to USDT."""

    sys.modules.pop("arbit.config", None)
    importlib.import_module("arbit.config")
    from arbit.adapters import alpaca_adapter as aa

    monkeypatch.setattr(aa, "TradingClient", DummyTradingClient)
    monkeypatch.setattr(aa, "CryptoHistoricalDataClient", DummyHistClient)
    monkeypatch.setattr(aa, "CryptoDataStream", FakeStream)
    monkeypatch.setattr(
        aa, "settings", SimpleNamespace(alpaca_base_url="", alpaca_map_usdt_to_usd=True)
    )
    adapter = aa.AlpacaAdapter("k", "s")

    async def run() -> None:
        gen = adapter.orderbook_stream(["BTC/USDT"], depth=1, reconnect_delay=0)
        sym1, _ = await asyncio.wait_for(anext(gen), timeout=1)
        sym2, _ = await asyncio.wait_for(anext(gen), timeout=1)
        await gen.aclose()
        assert sym1 == sym2 == "BTC/USDT"
        assert FakeStream.instances[0].symbols == ("BTC/USD",)
        assert len(FakeStream.instances) >= 2

    asyncio.run(run())
