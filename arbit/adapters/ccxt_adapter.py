"""Ccxt-based adapter implementing the :class:`ExchangeAdapter` interface.

This adapter now supports streaming market data via ``ccxt.pro`` WebSocket
feeds when available.  A lightweight REST polling fallback is provided for
environments where the websocket client is missing or an exchange does not
expose a stream.
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator, Iterable

import ccxt

try:  # pragma: no cover - optional dependency
    import ccxt.pro as ccxtpro
except Exception:  # pragma: no cover - websockets optional
    ccxtpro = None

from arbit.adapters.base import ExchangeAdapter, OrderSpec
from arbit.config import creds_for, settings


class CcxtAdapter(ExchangeAdapter):
    """Exchange adapter backed by the ``ccxt`` library."""

    def __init__(self, ex_id: str):
        """Initialise the underlying ccxt client for *ex_id*.

        The Alpaca adapter allows the trader API base URL to be customised via
        :class:`arbit.config.Settings` so that paper trading or alternative
        endpoints can be targeted.
        """
        key, sec = creds_for(ex_id)
        cls = getattr(ccxt, ex_id)
        self.ex = cls({"apiKey": key, "secret": sec, "enableRateLimit": True})
        self.ex_ws = None
        if ccxtpro is not None:
            try:  # pragma: no cover - depends on optional lib
                ws_cls = getattr(ccxtpro, ex_id)
                self.ex_ws = ws_cls(
                    {"apiKey": key, "secret": sec, "enableRateLimit": True}
                )
            except AttributeError:
                self.ex_ws = None
        if ex_id == "alpaca" and settings.alpaca_base_url:
            # Some venues like Alpaca use non-ccxt defaults; allow override.
            api_urls = self.ex.urls.get("api")
            if isinstance(api_urls, dict):
                api_urls["trader"] = settings.alpaca_base_url
            else:  # pragma: no cover - legacy ccxt versions
                self.ex.urls["api"] = settings.alpaca_base_url
        self._fee = {}

    def name(self):
        """Return the exchange identifier."""
        return self.ex.id

    def fetch_orderbook(self, symbol, depth=10):
        """Return order book for *symbol* limited to *depth* levels."""
        return self.ex.fetch_order_book(symbol, depth)

    def fetch_fees(self, symbol):
        """Return ``(maker, taker)`` fees for *symbol*, caching results."""
        if symbol in self._fee:
            return self._fee[symbol]
        m = self.ex.market(symbol)
        maker = m.get("maker", self.ex.fees.get("trading", {}).get("maker", 0.001))
        taker = m.get("taker", self.ex.fees.get("trading", {}).get("taker", 0.001))
        self._fee[symbol] = (maker, taker)
        return maker, taker

    def min_notional(self, symbol):
        """Return exchange-imposed minimum notional for *symbol*."""
        m = self.ex.market(symbol)
        return float(m.get("limits", {}).get("cost", {}).get("min", 1.0))

    def create_order(self, spec: OrderSpec):
        """Place an order described by *spec* and return a fill-like mapping."""
        # Dry-run → synthesize taker fill at top-of-book.
        if settings.dry_run:
            ob = self.fetch_orderbook(spec.symbol, 1)
            price = ob["asks"][0][0] if spec.side == "buy" else ob["bids"][0][0]
            fee = self.fetch_fees(spec.symbol)[1] * price * spec.qty
            return {
                "id": "dryrun",
                "symbol": spec.symbol,
                "side": spec.side,
                "qty": spec.qty,
                "price": price,
                "fee": fee,
            }

        params = {"timeInForce": spec.tif}
        o = self.ex.create_order(
            spec.symbol, spec.type, spec.side, spec.qty, None, params
        )
        filled = float(o.get("filled", spec.qty))
        price = float(o.get("average") or o.get("price") or 0.0)
        fee_cost = sum(float(f.get("cost") or 0) for f in o.get("fees", []))
        return {
            "id": o["id"],
            "symbol": spec.symbol,
            "side": spec.side,
            "qty": filled,
            "price": price,
            "fee": fee_cost,
        }

    def balances(self):
        """Return assets with non-zero balances."""
        b = self.ex.fetch_balance()
        return {k: float(v) for k, v in b.get("total", {}).items() if float(v or 0) > 0}

    async def orderbook_stream(
        self,
        symbols: Iterable[str],
        depth: int = 10,
        poll_interval: float = 1.0,
    ) -> AsyncGenerator[tuple[str, dict], None]:
        """Yield order book updates for ``symbols``.

        When a websocket client is available, ``ccxt.pro``'s
        ``watch_order_book`` coroutine is used.  Otherwise, order books are
        polled via the REST ``fetch_order_book`` endpoint using
        :func:`asyncio.to_thread` to avoid blocking the event loop.

        Parameters
        ----------
        symbols:
            Symbols to monitor for order book updates.
        depth:
            Maximum number of levels to request per book.
        poll_interval:
            Delay between REST polling cycles when websockets are unavailable.
        """

        syms = list(symbols)
        if self.ex_ws is not None and hasattr(self.ex_ws, "watch_order_book"):
            while True:
                for sym in syms:
                    ob = await self.ex_ws.watch_order_book(sym, depth)  # type: ignore[attr-defined]
                    yield sym, ob
        else:
            while True:
                for sym in syms:
                    ob = await asyncio.to_thread(self.fetch_orderbook, sym, depth)
                    yield sym, ob
                await asyncio.sleep(poll_interval)


# Backwards compatibility for older tests expecting ``CCXTAdapter``
CCXTAdapter = CcxtAdapter

