"""Tests for streaming utilities and WebSocket integration."""

import asyncio
from builtins import anext
from types import SimpleNamespace

from arbit.engine import executor
from arbit.models import Triangle
from tests.alpaca_mocks import MockDataStream


class DummyStream:
    """Minimal Alpaca websocket stub."""

    def __init__(
        self,
        key: str,
        secret: str,
        *,
        url: str | None = None,
        data_feed: str | None = None,
        **_: object,
    ) -> None:  # pragma: no cover - trivial
        self.handler = None
        self.url = url
        self.data_feed = data_feed

    def subscribe_orderbooks(self, handler, *symbols) -> None:
        self.handler = handler

    async def _run_forever(self) -> None:  # pragma: no cover - trivial
        await self.handler(SimpleNamespace(symbol="BTC/USDT", bids=[], asks=[]))

    def stop(self) -> None:  # pragma: no cover - trivial
        pass


class DummyClient:
    """Minimal client stub used to satisfy adapter dependencies."""

    def __init__(self, *args, **kwargs) -> None:  # pragma: no cover - trivial
        pass


def test_ccxt_orderbook_stream_falls_back_to_rest(monkeypatch) -> None:
    """When ``watch_order_book`` errors the CCXT adapter uses REST polling."""

    import arbit.adapters.ccxt_adapter as ca

    class StubRestExchange:
        def __init__(self, *_: object, **__: object) -> None:
            self.options: dict[str, object] = {}
            self.id = "stub"

        def fetch_order_book(self, symbol: str, depth: int) -> dict:
            return {
                "symbol": symbol,
                "bids": [[1.0, depth]],
                "asks": [[2.0, depth]],
                "source": "rest",
            }

    class StubWebSocket:
        def __init__(self, *_: object, **__: object) -> None:
            self.closed = False

        async def watch_order_book(self, symbol: str, depth: int) -> dict:
            raise RuntimeError(f"{symbol} unsupported")

        async def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(ca, "ccxt", SimpleNamespace(stub=StubRestExchange))
    monkeypatch.setattr(ca, "ccxtpro", SimpleNamespace(stub=StubWebSocket))
    monkeypatch.setattr(ca, "creds_for", lambda ex: ("k", "s"))

    adapter = ca.CCXTAdapter("stub")

    async def run() -> None:
        stream = adapter.orderbook_stream(["BTC/USDT"], depth=1, poll_interval=0.0)
        sym1, book1 = await asyncio.wait_for(anext(stream), timeout=1.0)
        assert sym1 == "BTC/USDT"
        assert "error" in book1
        sym2, book2 = await asyncio.wait_for(anext(stream), timeout=1.0)
        assert sym2 == "BTC/USDT"
        assert book2.get("source") == "rest"
        await stream.aclose()

    asyncio.run(run())


def test_orderbook_stream_emits_updates(monkeypatch) -> None:
    """The Alpaca adapter streams order book updates via websocket."""

    import sys

    sys.modules.pop("arbit.adapters.alpaca_adapter", None)
    import arbit.adapters.alpaca_adapter as aa

    monkeypatch.setattr(aa, "TradingClient", DummyClient)
    monkeypatch.setattr(aa, "CryptoHistoricalDataClient", DummyClient)
    monkeypatch.setattr(aa, "CryptoDataStream", DummyStream)
    monkeypatch.setattr(
        aa,
        "settings",
        SimpleNamespace(
            alpaca_base_url="",
            alpaca_map_usdt_to_usd=False,
            alpaca_ws_crypto_url="wss://stream.data.alpaca.markets/v1beta3/crypto/us",
            alpaca_data_feed="us",
        ),
    )
    monkeypatch.setattr(aa, "creds_for", lambda ex: ("k", "s"))

    adapter = aa.AlpacaAdapter()

    async def run() -> None:
        stream = adapter.orderbook_stream(["BTC/USDT"], depth=1, reconnect_delay=0)
        symbol, book = await anext(stream)
        assert symbol == "BTC/USDT"
        assert book == {"bids": [], "asks": []}
        await stream.aclose()

    asyncio.run(run())


def test_orderbook_stream_quiet_symbol(monkeypatch) -> None:
    """A silent symbol should not block updates for active books."""

    import sys

    sys.modules.pop("arbit.adapters.alpaca_adapter", None)
    import arbit.adapters.alpaca_adapter as aa

    class QuietStream:
        def __init__(
            self,
            key: str,
            secret: str,
            *,
            url: str | None = None,
            data_feed: str | None = None,
            **_: object,
        ) -> None:
            self.handler = None
            self.url = url
            self.data_feed = data_feed

        def subscribe_orderbooks(self, handler, *symbols) -> None:
            self.handler = handler

        async def _run_forever(self) -> None:
            await asyncio.sleep(0.01)
            await self.handler(SimpleNamespace(symbol="BTC/USDT", bids=[], asks=[]))
            await asyncio.sleep(0.2)
            await self.handler(SimpleNamespace(symbol="ETH/USDT", bids=[], asks=[]))

        def stop(self) -> None:  # pragma: no cover - trivial
            pass

    monkeypatch.setattr(aa, "TradingClient", DummyClient)
    monkeypatch.setattr(aa, "CryptoHistoricalDataClient", DummyClient)
    monkeypatch.setattr(aa, "CryptoDataStream", QuietStream)
    monkeypatch.setattr(
        aa,
        "settings",
        SimpleNamespace(
            alpaca_base_url="",
            alpaca_map_usdt_to_usd=False,
            alpaca_ws_crypto_url="wss://stream.data.alpaca.markets/v1beta3/crypto/us",
            alpaca_data_feed="us",
        ),
    )
    monkeypatch.setattr(aa, "creds_for", lambda ex: ("k", "s"))
    adapter = aa.AlpacaAdapter()

    async def run() -> None:
        stream = adapter.orderbook_stream(
            ["ETH/USDT", "BTC/USDT"], depth=1, reconnect_delay=0
        )
        sym, _ = await asyncio.wait_for(anext(stream), timeout=0.1)
        assert sym == "BTC/USDT"
        await stream.aclose()

    asyncio.run(run())


def test_orderbook_stream_uses_configured_feed(monkeypatch) -> None:
    """Adapter passes configured websocket URL and data feed to Alpaca."""

    import sys

    sys.modules.pop("arbit.adapters.alpaca_adapter", None)
    import arbit.adapters.alpaca_adapter as aa

    MockDataStream.instances.clear()
    MockDataStream.updates_runs = [
        [SimpleNamespace(symbol="BTC/USDT", bids=[], asks=[])]
    ]
    MockDataStream.run_index = 0

    monkeypatch.setattr(aa, "TradingClient", DummyClient)
    monkeypatch.setattr(aa, "CryptoHistoricalDataClient", DummyClient)
    monkeypatch.setattr(aa, "CryptoDataStream", MockDataStream)
    monkeypatch.setattr(
        aa,
        "settings",
        SimpleNamespace(
            alpaca_base_url="",
            alpaca_map_usdt_to_usd=False,
            alpaca_ws_crypto_url="wss://example.test/crypto",
            alpaca_data_feed="sip",
        ),
    )
    monkeypatch.setattr(aa, "creds_for", lambda ex: ("k", "s"))

    adapter = aa.AlpacaAdapter()

    async def run() -> None:
        stream = adapter.orderbook_stream(["BTC/USDT"], depth=1, reconnect_delay=0)
        await anext(stream)
        await stream.aclose()

    asyncio.run(run())

    instance = MockDataStream.instances[-1]
    assert instance.url == "wss://example.test/crypto"
    assert instance.data_feed == "sip"


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

    def fake_try(adapter, tri, books, threshold, skip_reasons, skip_meta=None):
        return {"tri": tri, "net_est": 0.0, "fills": [], "realized_usdt": 0.0}

    monkeypatch.setattr(executor, "try_triangle", fake_try)

    async def run():
        gen = executor.stream_triangles(adapter, [tri], 0.0, depth=1)
        out = await anext(gen)
        assert out[0] == tri
        assert out[1]["tri"] == tri
        assert isinstance(out[4], dict)

    asyncio.run(run())
