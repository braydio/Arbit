"""CCXT based implementation of :class:`ExchangeAdapter`."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import ccxt  # type: ignore

from ..models import Fill, OrderSpec
from .base import ExchangeAdapter


class CCXTAdapter(ExchangeAdapter):
    """Adapter providing access to exchanges supported by `ccxt`.

    Currently limited to the ``alpaca`` and ``kraken`` exchanges.
    """

    def __init__(self, exchange_id: str, api_key: str, api_secret: str) -> None:
        """Instantiate adapter for the given *exchange_id*.

        Args:
            exchange_id: Identifier of the exchange (``alpaca`` or ``kraken``).
            api_key: API key for authentication.
            api_secret: API secret for authentication.
        """
        if exchange_id not in {"alpaca", "kraken"}:
            raise ValueError(f"Unsupported exchange: {exchange_id}")

        exchange_cls = getattr(ccxt, exchange_id)
        self.client = exchange_cls(
            {
                "apiKey": api_key,
                "secret": api_secret,
                "enableRateLimit": True,
            }
        )

    def fetch_order_book(self, symbol: str) -> dict[str, Any]:
        """Return the current order book for *symbol*."""
        return self.client.fetch_order_book(symbol)

    def create_order(self, order: OrderSpec) -> Fill:
        """Place *order* on the exchange and return fill details."""
        result = self.client.create_order(
            order.symbol, order.order_type, order.side, order.quantity, order.price
        )
        timestamp = result.get("timestamp")
        ts = datetime.fromtimestamp(timestamp / 1000) if timestamp else None
        fee_cost = 0.0
        fee = result.get("fee")
        if isinstance(fee, dict):
            fee_cost = float(fee.get("cost", 0))
        return Fill(
            order_id=str(result.get("id")),
            symbol=order.symbol,
            side=order.side,
            price=float(result.get("price") or 0),
            quantity=float(result.get("amount") or order.quantity),
            fee=fee_cost,
            timestamp=ts,
        )

    def cancel_order(self, order_id: str, symbol: str) -> None:
        """Cancel an open order on the exchange."""
        self.client.cancel_order(order_id, symbol)

    def fetch_balance(self, asset: str) -> float:
        """Return available balance for *asset*."""
        balance = self.client.fetch_balance()
        return float(balance.get("free", {}).get(asset, 0))
