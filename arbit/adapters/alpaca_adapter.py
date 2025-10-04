"""Alpaca adapter leveraging official alpaca-py clients.

This module provides :class:`AlpacaAdapter` which implements the
:class:`~arbit.adapters.base.ExchangeAdapter` interface using Alpaca's
``alpaca-py`` REST and websocket clients. The implementation focuses on
crypto trading and market-data features required by the CLI tools.

The adapter exposes synchronous helpers like :meth:`fetch_orderbook`
for REST access and an asynchronous :meth:`orderbook_stream` for realtime
book updates.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, AsyncGenerator, Dict, Iterable, Tuple

from arbit.adapters.base import ExchangeAdapter, OrderSpec
from arbit.config import creds_for, settings

try:  # pragma: no cover - optional dependency
    from alpaca.data.historical import CryptoHistoricalDataClient
    from alpaca.data.live import CryptoDataStream
    from alpaca.data.requests import CryptoLatestOrderbookRequest
    from alpaca.trading.client import TradingClient
    from alpaca.trading.enums import AssetClass, AssetStatus, OrderSide, TimeInForce
    from alpaca.trading.requests import GetAssetsRequest, MarketOrderRequest
except Exception:  # pragma: no cover - dependency may be absent
    TradingClient = None  # type: ignore
    MarketOrderRequest = None  # type: ignore
    GetAssetsRequest = None  # type: ignore
    AssetClass = AssetStatus = OrderSide = TimeInForce = None  # type: ignore
    CryptoHistoricalDataClient = None  # type: ignore
    CryptoLatestOrderbookRequest = None  # type: ignore
    CryptoDataStream = None  # type: ignore


class AlpacaAdapter(ExchangeAdapter):
    """Exchange adapter implemented using Alpaca's official clients."""

    def __init__(self, key: str | None = None, secret: str | None = None):
        if TradingClient is None:  # pragma: no cover - defensive
            raise RuntimeError("alpaca-py dependency not available")

        if key is None or secret is None:
            key, secret = creds_for("alpaca")
        base_url = getattr(settings, "alpaca_base_url", None)
        paper_mode = "paper" in (base_url or "")
        self._key = key
        self._secret = secret
        trading_kwargs: dict[str, Any] = {"paper": paper_mode}
        if base_url:
            trading_kwargs["base_url"] = base_url
        try:
            self.trading = TradingClient(key, secret, **trading_kwargs)
        except TypeError as exc:  # alpaca-py<=0.18 lacks base_url kwarg
            if "base_url" not in str(exc) or "base_url" not in trading_kwargs:
                raise
            trading_kwargs.pop("base_url", None)
            self.trading = TradingClient(key, secret, **trading_kwargs)
        self.data = CryptoHistoricalDataClient(key, secret)
        self._stream: CryptoDataStream | None = None
        # expose self as `.ex` so CLI can call `a.ex.load_markets()`
        self.ex = self
        self._markets: dict[str, dict[str, Any]] | None = None

    # ------------------------------------------------------------------
    def name(self) -> str:
        """Return the exchange identifier."""

        return "alpaca"

    # ------------------------------------------------------------------
    def fetch_orderbook(self, symbol: str, depth: int = 10) -> Dict[str, Any]:
        """Fetch latest order book for *symbol* limited to *depth* levels."""

        if settings.alpaca_map_usdt_to_usd and symbol.upper().endswith("/USDT"):
            req_symbol = symbol[:-5] + "/USD"
        else:
            req_symbol = symbol
        if CryptoLatestOrderbookRequest is None:  # pragma: no cover - defensive
            raise RuntimeError("alpaca-py dependency not available")
        req = CryptoLatestOrderbookRequest(symbol_or_symbols=req_symbol)
        ob = self.data.get_crypto_latest_orderbook(req)[req_symbol]
        bids = [[b.p, b.s] for b in getattr(ob, "bids", [])][:depth]
        asks = [[a.p, a.s] for a in getattr(ob, "asks", [])][:depth]
        return {"bids": bids, "asks": asks}

    # ------------------------------------------------------------------
    def fetch_fees(self, symbol: str) -> Tuple[float, float]:
        """Return ``(maker, taker)`` fee rates for *symbol*.

        Alpaca currently charges no maker fee and 0.01% taker fee for crypto.
        """

        return 0.0, 0.0001

    # ------------------------------------------------------------------
    def min_notional(self, symbol: str) -> float:
        """Return smallest notional value accepted by Alpaca."""

        return 1.0

    # ------------------------------------------------------------------
    def create_order(self, spec: OrderSpec) -> Dict[str, Any]:
        """Submit an order described by *spec* and return execution info."""

        if settings.dry_run:
            ob = self.fetch_orderbook(spec.symbol, 1)
            price = ob["asks"][0][0] if spec.side == "buy" else ob["bids"][0][0]
            fee = self.fetch_fees(spec.symbol)[1] * price * spec.qty
            return {
                "id": "dryrun",
                "symbol": spec.symbol,
                "side": spec.side,
                "price": price,
                "qty": spec.qty,
                "fee": fee,
            }

        if MarketOrderRequest is None:  # pragma: no cover - defensive
            raise RuntimeError("alpaca-py dependency not available")
        symbol = spec.symbol
        if settings.alpaca_map_usdt_to_usd and symbol.upper().endswith("/USDT"):
            symbol = symbol[:-5] + "/USD"
        order = MarketOrderRequest(
            symbol=symbol,
            qty=spec.qty,
            side=OrderSide.BUY if spec.side == "buy" else OrderSide.SELL,
            time_in_force=TimeInForce.IOC,
        )
        res = self.trading.submit_order(order)
        price = float(getattr(res, "filled_avg_price", 0.0) or 0.0)
        return {
            "id": getattr(res, "id", ""),
            "symbol": spec.symbol,
            "side": spec.side,
            "price": price,
            "qty": float(getattr(res, "filled_qty", spec.qty) or spec.qty),
            "fee": 0.0,
        }

    # ------------------------------------------------------------------
    def balances(self) -> Dict[str, float]:
        """Return asset balances with non-zero amounts."""

        bals: Dict[str, float] = {}
        try:
            for p in self.trading.get_all_positions():
                bals[p.symbol] = float(getattr(p, "qty", 0.0))
            acct = self.trading.get_account()
            bals[getattr(acct, "currency", "USD")] = float(getattr(acct, "cash", 0.0))
        except Exception as exc:  # pragma: no cover - network errors
            logging.getLogger("arbit").debug("balances fetch failed: %s", exc)
        return {k: v for k, v in bals.items() if v}

    # ------------------------------------------------------------------
    def fetch_balance(self, asset: str) -> float:
        """Return free balance for *asset* in its native units."""

        return self.balances().get(asset, 0.0)

    # ------------------------------------------------------------------
    async def orderbook_stream(
        self, symbols: Iterable[str], depth: int = 10, reconnect_delay: float = 1.0
    ) -> AsyncGenerator[Tuple[str, Dict[str, Any]], None]:
        """Yield ``(symbol, order_book)`` updates for *symbols*.

        The adapter automatically reconnects when the underlying stream
        terminates or errors. Each yielded ``book`` is a dictionary with
        ``bids`` and ``asks`` lists limited to *depth* levels.
        """

        if CryptoDataStream is None:  # pragma: no cover - defensive
            raise RuntimeError("alpaca-py dependency not available")

        mapped: Dict[str, str] = {}
        sub_syms: list[str] = []
        for sym in symbols:
            if settings.alpaca_map_usdt_to_usd and sym.upper().endswith("/USDT"):
                alt = sym[:-5] + "/USD"
                mapped[alt] = sym
                sub_syms.append(alt)
            else:
                sub_syms.append(sym)

        queue: asyncio.Queue[Tuple[str, Dict[str, Any]]] = asyncio.Queue()

        async def _handler(data: Any) -> None:
            sym = getattr(data, "symbol", "")
            out_sym = mapped.get(sym, sym)
            bids = [[b.p, b.s] for b in getattr(data, "bids", [])][:depth]
            asks = [[a.p, a.s] for a in getattr(data, "asks", [])][:depth]
            await queue.put((out_sym, {"bids": bids, "asks": asks}))

        ws_kwargs: dict[str, Any] = {}
        ws_url = getattr(settings, "alpaca_ws_crypto_url", None)
        ws_feed = getattr(settings, "alpaca_data_feed", None)
        try:
            sig = inspect.signature(CryptoDataStream)
        except Exception:
            sig = None
        params = sig.parameters if sig else {}
        if ws_url:
            if "url_override" in params:
                ws_kwargs["url_override"] = ws_url
            elif "url" in params:
                ws_kwargs["url"] = ws_url
        if ws_feed:
            target_key = None
            if "feed" in params:
                target_key = "feed"
            elif "data_feed" in params:
                target_key = "data_feed"
            if target_key:
                try:
                    from alpaca.data.enums import CryptoFeed  # type: ignore

                    if isinstance(ws_feed, str):
                        candidate = ws_feed.strip()
                        ws_kwargs[target_key] = CryptoFeed(candidate)  # type: ignore[arg-type]
                    else:
                        ws_kwargs[target_key] = ws_feed
                except Exception:
                    ws_kwargs[target_key] = ws_feed

        while True:
            stream = CryptoDataStream(
                self._key,
                self._secret,
                **ws_kwargs,
            )
            self._stream = stream

            # Subscribe using the most compatible method available across alpaca-py versions.
            subscribed = False
            try:
                # Older signatures accept a handler as the first argument.
                stream.subscribe_orderbooks(_handler, *sub_syms)  # type: ignore[misc]
                subscribed = True
            except TypeError:
                # Newer alpaca-py requires setting a handler via set_handlers(...) and
                # subscribing with symbols only.
                try:
                    stream.subscribe_orderbooks(*sub_syms)  # type: ignore[misc]
                    # Try the common handler key names used by alpaca-py releases.
                    if hasattr(stream, "set_handlers") and callable(stream.set_handlers):
                        try:
                            # Prefer the explicit on_orderbook keyword when available.
                            stream.set_handlers(on_orderbook=_handler)  # type: ignore[call-arg]
                        except TypeError:
                            # Fallback: some versions accept 'orderbook' instead.
                            stream.set_handlers(orderbook=_handler)  # type: ignore[call-arg]
                    subscribed = True
                except Exception:
                    # As a last resort, try the original path again to surface a useful error below.
                    try:
                        stream.subscribe_orderbooks(_handler, *sub_syms)  # type: ignore[misc]
                        subscribed = True
                    except Exception:
                        subscribed = False

            # Choose the appropriate run coroutine across versions.
            async def _run_stream() -> None:
                # Prefer public run() if present; fall back to private _run_forever().
                runner = getattr(stream, "run", None)
                if callable(runner):
                    res = runner()
                    if inspect.isawaitable(res):
                        await res
                        return
                runner = getattr(stream, "_run_forever", None)
                if callable(runner):
                    res = runner()
                    if inspect.isawaitable(res):
                        await res
                        return
                # If no runnable coroutine exists, yield nothing and exit.
                raise RuntimeError("alpaca CryptoDataStream lacks run coroutine")

            run_task = asyncio.create_task(_run_stream())
            get_task = asyncio.create_task(queue.get())
            try:
                while True:
                    done, _ = await asyncio.wait(
                        {run_task, get_task}, return_when=asyncio.FIRST_COMPLETED
                    )
                    if get_task in done:
                        yield get_task.result()
                        get_task = asyncio.create_task(queue.get())
                    if run_task in done:
                        run_task.result()
                        break
            except Exception:
                logging.getLogger("arbit").debug(
                    "alpaca stream reconnecting", exc_info=True
                )
            finally:
                run_task.cancel()
                get_task.cancel()
                await asyncio.gather(run_task, get_task, return_exceptions=True)
                try:
                    stream.stop()  # type: ignore[attr-defined]
                except Exception:
                    pass
                await asyncio.sleep(reconnect_delay)

    # ------------------------------------------------------------------
    async def close(self) -> None:
        """Close any open network resources."""

        if self._stream is not None:
            try:
                self._stream.stop()  # type: ignore[attr-defined]
            except Exception:
                pass
            self._stream = None

    # ------------------------------------------------------------------
    def load_markets(self) -> Dict[str, Any]:
        """Return mapping of tradeable pairs via the Alpaca REST API."""

        if self._markets is not None:
            return self._markets
        if GetAssetsRequest is None:  # pragma: no cover - defensive
            raise RuntimeError("alpaca-py dependency not available")
        req = GetAssetsRequest(status=AssetStatus.ACTIVE, asset_class=AssetClass.CRYPTO)
        markets: Dict[str, Dict[str, Any]] = {}
        try:
            assets = self.trading.get_all_assets(req)
            for a in assets:
                sym = getattr(a, "symbol", "")
                if sym.endswith("USD"):
                    pair = sym[:-3] + "/USD"
                    markets[pair] = {"symbol": pair}
                    if settings.alpaca_map_usdt_to_usd:
                        usdt = pair.replace("/USD", "/USDT")
                        markets[usdt] = {"symbol": usdt}
        except Exception as exc:  # pragma: no cover - network errors
            logging.getLogger("arbit").debug("load_markets failed: %s", exc)
        self._markets = markets
        return markets
