from abc import ABC, abstractmethod
from typing import Any, Dict, Tuple
from dataclasses import dataclass
from typing import Literal

Side = Literal["buy", "sell"]


@dataclass
class OrderSpec:
    symbol: str
    side: Side
    qty: float
    tif: str = "IOC"  # time in force
    type: str = "market"  # market for speed; upgrade later


class ExchangeAdapter(ABC):
    @abstractmethod
    def name(self) -> str: ...
    @abstractmethod
    def fetch_orderbook(self, symbol: str, depth: int = 10) -> Dict[str, Any]: ...
    @abstractmethod
    def fetch_fees(self, symbol: str) -> Tuple[float, float]: ...
    @abstractmethod
    def min_notional(self, symbol: str) -> float: ...
    @abstractmethod
    def create_order(self, spec: OrderSpec): ...
    @abstractmethod
    def balances(self) -> Dict[str, float]: ...
