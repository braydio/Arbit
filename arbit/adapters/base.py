"""Abstract base classes for exchange connectivity."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..models import Fill, OrderSpec


class ExchangeAdapter(ABC):
    """Abstract base class defining a minimal exchange interface."""

    @abstractmethod
    def fetch_order_book(self, symbol: str) -> dict[str, Any]:
        """Return the current order book for *symbol*."""

    @abstractmethod
    def create_order(self, order: OrderSpec) -> Fill:
        """Place an *order* on the exchange and return a :class:`~arbit.models.Fill`."""

    @abstractmethod
    def cancel_order(self, order_id: str, symbol: str) -> None:
        """Cancel an open order identified by *order_id* on *symbol*."""

    @abstractmethod
    def fetch_balance(self, asset: str) -> float:
        """Return available balance for the given *asset*."""
