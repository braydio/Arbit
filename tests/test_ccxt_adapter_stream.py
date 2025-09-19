"""Tests for the CCXT adapter websocket order book stream."""

import asyncio
import sys
import types
from builtins import anext
from types import SimpleNamespace
from typing import Dict, Iterable

import pytest

try:  # pragma: no cover - optional dependency may be unavailable during tests
    import ccxt  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - inject lightweight stub
    ccxt_module = types.ModuleType("ccxt")
    sys.modules["ccxt"] = ccxt_module
    sys.modules.setdefault("ccxt.pro", types.ModuleType("ccxt.pro"))

from arbit.adapters.ccxt_adapter import CCXTAdapter


class FakeProClient:
    """Minimal ``ccxt.pro``-style client returning queued order books."""

    def __init__(self, symbols: Iterable[str]):
        self.queues: Dict[str, asyncio.Queue] = {
            sym: asyncio.Queue() for sym in symbols
        }
        self.call_count: Dict[str, int] = {sym: 0 for sym in symbols}
        self.closed = False

    async def watch_order_book(self, symbol: str, depth: int) -> dict:
        self.call_count[symbol] += 1
        return await self.queues[symbol].get()

    def publish(self, symbol: str, book: dict) -> None:
        """Push *book* onto the queue for *symbol*."""

        self.queues[symbol].put_nowait(book)

    def close(self):  # pragma: no cover - synchronous close helper
        self.closed = True
        return None


def test_orderbook_stream_preserves_symbol_tasks() -> None:
    """Each symbol continues streaming even as other books update."""

    async def run() -> None:
        symbols = ("BTC/USDT", "ETH/USDT", "SOL/USDT")
        fake_ws = FakeProClient(symbols)

        adapter = CCXTAdapter.__new__(CCXTAdapter)
        adapter.ex = SimpleNamespace(id="demo")  # type: ignore[attr-defined]
        adapter.ex_ws = fake_ws  # type: ignore[attr-defined]

        stream = adapter.orderbook_stream(symbols, depth=1)

        try:
            first = asyncio.create_task(anext(stream))
            await asyncio.sleep(0)
            fake_ws.publish(symbols[0], {"bids": [[1, 1]], "asks": [[1, 1]]})
            sym, _ = await asyncio.wait_for(first, timeout=0.1)
            assert sym == symbols[0]
            assert fake_ws.call_count[symbols[1]] == 1
            assert fake_ws.call_count[symbols[2]] == 1

            second = asyncio.create_task(anext(stream))
            await asyncio.sleep(0)
            fake_ws.publish(symbols[1], {"bids": [[2, 1]], "asks": [[2, 1]]})
            sym, _ = await asyncio.wait_for(second, timeout=0.1)
            assert sym == symbols[1]
            assert fake_ws.call_count[symbols[2]] == 1

            third = asyncio.create_task(anext(stream))
            await asyncio.sleep(0)
            fake_ws.publish(symbols[2], {"bids": [[3, 1]], "asks": [[3, 1]]})
            sym, _ = await asyncio.wait_for(third, timeout=0.1)
            assert sym == symbols[2]
        finally:
            await stream.aclose()

        # After closing the stream the websocket client should have been closed.
        assert fake_ws.closed is True

    asyncio.run(run())
