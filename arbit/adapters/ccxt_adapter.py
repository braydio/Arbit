"""Ccxt-based adapter implementing the :class:`ExchangeAdapter` interface.

This adapter now supports streaming market data via ``ccxt.pro`` WebSocket
feeds when available.  A lightweight REST polling fallback is provided for
environments where the websocket client is missing or an exchange does not
expose a stream.
"""

from __future__ import annotations

import asyncio
from typing import AsyncGenerator, Iterable
import logging

import ccxt

try:  # pragma: no cover - optional dependency
    import ccxt.pro as ccxtpro  # noqa: F401
except Exception:  # pragma: no cover - ccxt.pro may be unavailable
    ccxtpro = None

from arbit.adapters.base import ExchangeAdapter
from arbit.config import creds_for, settings
from arbit.models import Fill  # retained for type parity elsewhere (not returned here)


class CCXTAdapter(ExchangeAdapter):
    """Exchange adapter backed by the ``ccxt`` library."""

    def __init__(self, ex_id: str, key: str | None = None, secret: str | None = None):
        """Initialise the underlying ccxt client for *ex_id*.

        Parameters
        ----------
        ex_id:
            Exchange identifier recognised by ``ccxt``.
        key, secret:
            API credentials. When omitted, :func:`arbit.config.creds_for`
            provides them so production code can rely on environment
            configuration.

        The Alpaca adapter allows the trader API base URL to be customised via
        :class:`arbit.config.Settings` so that paper trading or alternative
        endpoints can be targeted.
        """
        # Normalize exchange id from env/user input (strip quotes/whitespace)
        ex_id = (ex_id or "").strip().strip("'\"").lower()

        if key is None or secret is None:
            key, secret = creds_for(ex_id)
        cls = getattr(ccxt, ex_id)
        self.ex = cls({"apiKey": key, "secret": secret, "enableRateLimit": True})
        # Hint ccxt to use trading endpoints where relevant (helps Alpaca crypto)
        try:
            opts = dict(getattr(self.ex, "options", {}) or {})
            opts.setdefault("defaultType", "trading")
            self.ex.options = opts
        except Exception:
            pass
        self.client = self.ex
        # Optional: initialise ccxt.pro client for websocket support when available
        self.ex_ws = None
        try:  # pragma: no cover - depends on optional ccxt.pro
            if ccxtpro is not None:
                ws_cls = getattr(ccxtpro, ex_id, None)
                if ws_cls is not None:
                    self.ex_ws = ws_cls({"apiKey": key, "secret": secret})
        except Exception:
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
        try:
            return self.ex.fetch_order_book(symbol, depth)
        except Exception as e:
            # Optional Alpaca quirk: map USDT-quoted to USD-quoted pairs for book-only
            try:
                if (
                    getattr(self.ex, "id", "").lower() == "alpaca"
                    and getattr(settings, "alpaca_map_usdt_to_usd", False)
                    and isinstance(symbol, str)
                    and symbol.upper().endswith("/USDT")
                ):
                    alt = symbol[:-5] + "/USD"
                    ob = self.ex.fetch_order_book(alt, depth)
                    logging.getLogger("arbit").debug(
                        "mapped %s -> %s for orderbook fetch", symbol, alt
                    )
                    return ob
            except Exception:
                pass
            logging.getLogger("arbit").debug(
                "fetch_orderbook error symbol=%s depth=%s: %s", symbol, depth, e
            )
            raise

    # Compatibility wrappers expected by tests -------------------------------------------------
    def fetch_order_book(self, symbol: str, depth: int = 10) -> dict:
        """Alias for :meth:`fetch_orderbook` using snake-case name."""

        return self.fetch_orderbook(symbol, depth)

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

    def create_order(self, spec) -> Fill:
        """Place an order described by *spec* and return a :class:`Fill`."""
        # Be robust to differing OrderSpec flavors (adapters.base vs models).
        if hasattr(spec, "qty"):
            qty = getattr(spec, "qty")
        elif hasattr(spec, "quantity"):
            qty = getattr(spec, "quantity")
        else:  # pragma: no cover - defensive
            raise AttributeError("OrderSpec missing qty/quantity")

        if hasattr(spec, "type"):
            order_type = getattr(spec, "type") or "market"
        else:
            order_type = getattr(spec, "order_type", "market")

        if settings.dry_run:
            ob = self.fetch_orderbook(spec.symbol, 1)
            price = ob["asks"][0][0] if spec.side == "buy" else ob["bids"][0][0]
            fee = self.fetch_fees(spec.symbol)[1] * price * qty
            return {
                "id": "dryrun",
                "symbol": spec.symbol,
                "side": spec.side,
                "price": price,
                "qty": qty,
                "fee": fee,
            }

        try:
            o = self.client.create_order(
                spec.symbol, order_type, spec.side, qty, spec.price or None
            )
        except Exception as e:
            logging.getLogger("arbit").error(
                "create_order failed symbol=%s side=%s qty=%s: %s",
                spec.symbol,
                spec.side,
                qty,
                e,
            )
            raise
        filled = float(o.get("filled", qty))
        price = float(o.get("average") or o.get("price") or 0.0)
        fee_cost = sum(float(f.get("cost") or 0) for f in o.get("fees", []))
        return {
            "id": o.get("id", ""),
            "symbol": spec.symbol,
            "side": spec.side,
            "price": price,
            "qty": filled,
            "fee": fee_cost,
        }

    async def orderbook_stream(
        self, symbols: Iterable[str], depth: int = 10, poll_interval: float = 1.0
    ) -> AsyncGenerator[tuple[str, dict], None]:
        """Yield ``(symbol, order_book)`` updates for *symbols*.

        Uses a websocket client if ``self.ex_ws`` is available; otherwise falls
        back to polling REST with ``poll_interval`` seconds between cycles.
        """

        # Track inter-update staleness
        last_ts: dict[str, float] = {}
        venue = getattr(self.ex, "id", "unknown")
        # Prefer websockets when available; otherwise poll REST
        if getattr(self, "ex_ws", None):
            try:
                while True:
                    try:
                        tasks = {
                            asyncio.create_task(self.ex_ws.watch_order_book(sym, depth)): sym
                            for sym in symbols
                        }
                        done, pending = await asyncio.wait(
                            tasks.keys(), return_when=asyncio.FIRST_COMPLETED
                        )
                        for t in done:
                            sym = tasks[t]
                            try:
                                ob = t.result()
                            except Exception as e:
                                logging.getLogger("arbit").debug(
                                    "ws watch_order_book error %s: %s", sym, e
                                )
                                ob = {"bids": [], "asks": [], "error": str(e)}
                            now = asyncio.get_event_loop().time()
                            prev = last_ts.get(sym)
                            if prev is not None:
                                try:
                                    from arbit.metrics.exporter import ORDERBOOK_STALENESS

                                    ORDERBOOK_STALENESS.labels(venue).observe(max(now - prev, 0.0))
                                except Exception:
                                    pass
                            last_ts[sym] = now
                            yield sym, ob
                        for t in pending:
                            t.cancel()
                        if pending:
                            try:
                                await asyncio.gather(*pending, return_exceptions=True)
                            except Exception:
                                pass
                    except Exception:
                        # WS failure – fall back to REST for a cycle before retrying
                        for sym in symbols:
                            try:
                                ob = self.fetch_orderbook(sym, depth)
                            except Exception as e:
                                ob = {"bids": [], "asks": [], "error": str(e)}
                            now = asyncio.get_event_loop().time()
                            prev = last_ts.get(sym)
                            if prev is not None:
                                try:
                                    from arbit.metrics.exporter import ORDERBOOK_STALENESS

                                    ORDERBOOK_STALENESS.labels(venue).observe(max(now - prev, 0.0))
                                except Exception:
                                    pass
                            last_ts[sym] = now
                            yield sym, ob
                        await asyncio.sleep(poll_interval)
            except asyncio.CancelledError:
                try:
                    # Close websocket client cleanly
                    close = getattr(self.ex_ws, "close", None)
                    if close:
                        res = close()
                        if asyncio.iscoroutine(res):
                            await res
                except Exception:
                    pass
                raise
        else:
            try:
                while True:
                    for sym in symbols:
                        try:
                            ob = self.fetch_orderbook(sym, depth)
                        except Exception as e:  # skip symbols that 404 or error
                            # Yield an empty book so callers can record a skip reason
                            ob = {"bids": [], "asks": [], "error": str(e)}
                        now = asyncio.get_event_loop().time()
                        prev = last_ts.get(sym)
                        if prev is not None:
                            try:
                                from arbit.metrics.exporter import ORDERBOOK_STALENESS

                                ORDERBOOK_STALENESS.labels(venue).observe(max(now - prev, 0.0))
                            except Exception:
                                pass
                        last_ts[sym] = now
                        yield sym, ob
                    await asyncio.sleep(poll_interval)
            except asyncio.CancelledError:
                raise

    async def close(self) -> None:
        """Close underlying exchange resources (REST + WebSocket)."""
        try:
            if getattr(self, "ex_ws", None):
                try:
                    res = self.ex_ws.close()
                    if asyncio.iscoroutine(res):
                        await res
                except Exception:
                    pass
        finally:
            try:
                if hasattr(self.ex, "close"):
                    self.ex.close()
            except Exception:
                pass

    def balances(self):
        """Return assets with non-zero balances."""
        b = self.ex.fetch_balance()
        return {k: float(v) for k, v in b.get("total", {}).items() if float(v or 0) > 0}

    # Additional convenience methods expected by tests ----------------------------------------
    def cancel_order(self, order_id: str, symbol: str) -> None:
        """Cancel order *order_id* for *symbol* on the exchange."""

        self.ex.cancel_order(order_id, symbol)

    def fetch_balance(self, asset: str) -> float:
        """Return free balance for *asset* in its native units."""

        return float(self.ex.fetch_balance().get("free", {}).get(asset, 0.0))


# Backwards compatible alias
CcxtAdapter = CCXTAdapter
