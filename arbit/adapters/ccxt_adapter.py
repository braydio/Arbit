"""Ccxt-based adapter implementing the ExchangeAdapter interface."""

import ccxt

from arbit.adapters.base import ExchangeAdapter
from arbit.config import creds_for, settings
from arbit.models import Fill, OrderSpec


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
        if key is None or secret is None:
            key, secret = creds_for(ex_id)
        cls = getattr(ccxt, ex_id)
        self.ex = cls({"apiKey": key, "secret": secret, "enableRateLimit": True})
        self.client = self.ex
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

    def create_order(self, spec: OrderSpec) -> Fill:
        """Place an order described by *spec* and return a :class:`Fill`."""
        qty = getattr(spec, "qty", getattr(spec, "quantity"))
        order_type = getattr(spec, "type", getattr(spec, "order_type", "market"))

        if settings.dry_run:
            ob = self.fetch_orderbook(spec.symbol, 1)
            price = ob["asks"][0][0] if spec.side == "buy" else ob["bids"][0][0]
            fee = self.fetch_fees(spec.symbol)[1] * price * qty
            return Fill(
                order_id="dryrun",
                symbol=spec.symbol,
                side=spec.side,
                price=price,
                quantity=qty,
                fee=fee,
            )

        o = self.client.create_order(
            spec.symbol, order_type, spec.side, qty, spec.price or None
        )
        filled = float(o.get("filled", qty))
        price = float(o.get("average") or o.get("price") or 0.0)
        fee_cost = sum(float(f.get("cost") or 0) for f in o.get("fees", []))
        return Fill(
            order_id=o["id"],
            symbol=spec.symbol,
            side=spec.side,
            price=price,
            quantity=filled,
            fee=fee_cost,
        )

    def balances(self):
        """Return assets with non-zero balances."""
        b = self.ex.fetch_balance()
        return {k: float(v) for k, v in b.get("total", {}).items() if float(v or 0) > 0}

    # Additional convenience methods expected by tests ----------------------------------------
    def cancel_order(self, order_id: str, symbol: str) -> None:
        """Cancel order *order_id* for *symbol* on the exchange."""

        self.ex.cancel_order(order_id, symbol)

    def fetch_balance(self, asset: str) -> float:
        """Return free balance for *asset*."""

        return float(self.ex.fetch_balance().get("free", {}).get(asset, 0.0))
