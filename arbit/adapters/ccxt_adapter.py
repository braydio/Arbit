"""Ccxt-based adapter implementing the ExchangeAdapter interface."""

import ccxt

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
