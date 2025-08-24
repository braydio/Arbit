from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class Triangle:
    AB: str  # e.g., ETH/USDT
    BC: str  # e.g., BTC/ETH
    AC: str  # e.g., BTC/USDT


def top(ob):
    bid = ob["bids"][0][0] if ob["bids"] else None
    ask = ob["asks"][0][0] if ob["asks"] else None
    return bid, ask


def net_edge(ask_AB: float, bid_BC: float, bid_AC: float, fee: float) -> float:
    gross = (1.0 / ask_AB) * bid_BC * bid_AC
    return gross * (1 - fee) ** 3 - 1.0


def size_from_depth(
    notional: float, best_ask_price: float, best_ask_qty: float
) -> float:
    if not best_ask_price or not best_ask_qty:
        return 0.0
    return min(notional / best_ask_price, best_ask_qty * 0.9)
