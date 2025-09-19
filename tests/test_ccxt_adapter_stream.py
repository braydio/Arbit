"""Tests covering CCXT adapter websocket streaming behaviour."""

import asyncio
from builtins import anext
from typing import Iterable

import pytest

import arbit.adapters.ccxt_adapter as ccxt_adapter_module


class DummyExchange:
    """Minimal ccxt exchange stub used for websocket streaming tests."""

    id = "dummy"

    def __init__(self, config: dict | None = None) -> None:
        self.config = config or {}
        self.id = "dummy"
        self.options: dict | None = {}
        self.fees = {"trading": {"maker": 0.0, "taker": 0.0}}

    def fetch_order_book(
        self, symbol: str, depth: int
    ) -> dict:  # pragma: no cover - defensive
        raise AssertionError("REST fallback should not be exercised in websocket tests")

    def market(self, symbol: str) -> dict:  # pragma: no cover - defensive
        return {"maker": 0.0, "taker": 0.0}


class FakeProClient:
    """Simulate ccxt.pro websocket client with controllable order book updates."""

    def __init__(self, symbols: Iterable[str]):
        self.symbols = list(symbols)
        self.waiters: dict[str, list[asyncio.Future]] = {
            sym: [] for sym in self.symbols
        }
        self.cancelled: dict[str, int] = {sym: 0 for sym in self.symbols}
        self.calls: dict[str, int] = {sym: 0 for sym in self.symbols}

    async def watch_order_book(self, symbol: str, depth: int) -> dict:
        self.calls[symbol] += 1
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self.waiters[symbol].append(fut)
        try:
            return await fut
        except asyncio.CancelledError:  # pragma: no cover - defensive
            self.cancelled[symbol] += 1
            raise

    async def publish(self, symbol: str, order_book: dict) -> None:
        while not self.waiters[symbol]:
            await asyncio.sleep(0)
        fut = self.waiters[symbol].pop(0)
        fut.set_result(order_book)


@pytest.mark.asyncio
async def test_orderbook_stream_keeps_symbol_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Websocket order books restart per symbol without cancelling other watchers."""

    symbols = ["BTC/USDT", "ETH/USDT", "LTC/USDT"]

    monkeypatch.setattr(
        ccxt_adapter_module, "creds_for", lambda ex_id: ("key", "secret")
    )
    monkeypatch.setattr(ccxt_adapter_module.ccxt, "dummy", DummyExchange)

    adapter = ccxt_adapter_module.CCXTAdapter("dummy")
    fake_ws = FakeProClient(symbols)
    adapter.ex_ws = fake_ws

    stream = adapter.orderbook_stream(symbols, depth=1)

    try:
        first = asyncio.create_task(anext(stream))
        await fake_ws.publish(symbols[0], {"bids": [[1, 1]], "asks": [[1, 1]]})
        sym, _ = await asyncio.wait_for(first, timeout=1)
        assert sym == symbols[0]
        assert (
            fake_ws.calls[symbols[0]] == 2
        )  # watcher restarted only for the active symbol
        assert fake_ws.calls[symbols[1]] == 1
        assert fake_ws.calls[symbols[2]] == 1
        assert fake_ws.cancelled[symbols[1]] == 0
        assert fake_ws.cancelled[symbols[2]] == 0

        second = asyncio.create_task(anext(stream))
        await fake_ws.publish(symbols[1], {"bids": [[2, 1]], "asks": [[2, 1]]})
        sym, _ = await asyncio.wait_for(second, timeout=1)
        assert sym == symbols[1]
        assert fake_ws.calls[symbols[1]] == 2
        assert fake_ws.calls[symbols[2]] == 1
        assert fake_ws.cancelled[symbols[2]] == 0

        third = asyncio.create_task(anext(stream))
        await fake_ws.publish(symbols[2], {"bids": [[3, 1]], "asks": [[3, 1]]})
        sym, _ = await asyncio.wait_for(third, timeout=1)
        assert sym == symbols[2]
    finally:
        await stream.aclose()
