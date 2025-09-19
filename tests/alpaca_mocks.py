"""Test doubles for Alpaca REST and websocket clients."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, List


class MockTradingClient:
    """Minimal trading client capturing method calls."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.submitted_orders: List[Any] = []
        self.positions_called = 0
        self.account_called = 0
        self.assets_called = 0

    # --- order endpoints -------------------------------------------------
    def submit_order(self, order: Any) -> Any:
        self.submitted_orders.append(order)
        return SimpleNamespace(id="ord1", filled_avg_price=1.0, filled_qty=order.qty)

    # --- account endpoints -----------------------------------------------
    def get_all_positions(self) -> List[Any]:
        self.positions_called += 1
        return [SimpleNamespace(symbol="BTCUSD", qty=0.5)]

    def get_account(self) -> Any:
        self.account_called += 1
        return SimpleNamespace(currency="USD", cash=100.0)

    def get_all_assets(self, req: Any) -> List[Any]:
        self.assets_called += 1
        return [SimpleNamespace(symbol="BTCUSD"), SimpleNamespace(symbol="ETHUSD")]


class MockHistClient:
    """Minimal historical data client."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover - trivial
        pass

    def get_crypto_latest_orderbook(self, req: Any) -> dict:
        sym = getattr(req, "symbol_or_symbols", "")
        return {sym: SimpleNamespace(bids=[], asks=[])}


class MockDataStream:
    """Websocket stream emitting predefined order book updates."""

    instances: List["MockDataStream"] = []
    updates_runs: List[List[Any]] = []
    run_index = 0

    def __init__(
        self,
        key: str,
        secret: str,
        *,
        url: str | None = None,
        data_feed: str | None = None,
        **_: Any,
    ) -> None:
        self.handler = None
        self.symbols: tuple[str, ...] = ()
        self.url = url
        self.data_feed = data_feed
        self.idx = MockDataStream.run_index
        MockDataStream.run_index += 1
        MockDataStream.instances.append(self)

    def subscribe_orderbooks(self, handler, *symbols: str) -> None:
        self.handler = handler
        self.symbols = symbols

    async def _run_forever(self) -> None:
        for ev in MockDataStream.updates_runs[self.idx]:
            await self.handler(ev)
        return

    def stop(self) -> None:  # pragma: no cover - trivial
        pass
