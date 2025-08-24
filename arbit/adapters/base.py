"""Abstract interfaces for exchange adapters."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, Tuple
from typing import Literal

Side = Literal["buy", "sell"]


@dataclass
class OrderSpec:
    """Parameters required to create an order on an exchange."""

    symbol: str
    side: Side
    qty: float
    tif: str = "IOC"  # time in force
    type: str = "market"  # market for speed; upgrade later


class ExchangeAdapter(ABC):
    """Interface that all exchange adapters must implement."""

    @abstractmethod
    def name(self) -> str:
        """Return exchange identifier used by this adapter."""

    @abstractmethod
    def fetch_orderbook(self, symbol: str, depth: int = 10) -> Dict[str, Any]:
        """Fetch order book levels for *symbol* up to *depth*."""

    @abstractmethod
    def fetch_fees(self, symbol: str) -> Tuple[float, float]:
        """Return ``(maker, taker)`` fee rates for *symbol*."""

    @abstractmethod
    def min_notional(self, symbol: str) -> float:
        """Smallest allowed notional value for trading *symbol*."""

    @abstractmethod
    def create_order(self, spec: OrderSpec):
        """Submit an order defined by *spec* to the exchange."""

    @abstractmethod
    def balances(self) -> Dict[str, float]:
        """Return asset balances with non-zero amounts."""
