"""Utility helpers for computing profitability and sizing in triangular markets."""

from typing import Iterable, List, Tuple


def top(levels: List[Tuple[float, float]]) -> Tuple[float | None, float | None]:
    """Return best bid and ask from a list of ``(bid, ask)`` tuples.

    Args:
        levels: Bid/ask pairs, typically from order book snapshots.

    Returns:
        A tuple ``(bid, ask)`` where ``bid`` is the highest bid price and
        ``ask`` is the lowest ask price. ``(None, None)`` is returned when no
        levels are supplied.
    """

    if not levels:
        return None, None

    bids = [b for b, _ in levels if b is not None]
    asks = [a for _, a in levels if a is not None]
    best_bid = max(bids) if bids else None
    best_ask = min(asks) if asks else None
    return best_bid, best_ask


def net_edge_cycle(rates: Iterable[float]) -> float:
    """Return the product of ``rates`` minus one.

    The ``rates`` are multiplicative factors representing conversion steps
    around a trading cycle. A value greater than zero indicates a profitable
    cycle before fees.
    """

    product = 1.0
    for r in rates:
        product *= r
    return product - 1.0


def net_edge(ask_AB: float, bid_BC: float, bid_AC: float, fee: float) -> float:
    """Compute the net edge for a triangular arbitrage opportunity.

    Args:
        ask_AB: Ask price for the AB pair.
        bid_BC: Bid price for the BC pair.
        bid_AC: Bid price for the AC pair.
        fee:    Fee rate applied to each trade (e.g., 0.001 for 0.1%).

    Returns:
        The estimated percentage gain over the cycle after accounting for
        trading fees.
    """

    return net_edge_cycle([1.0 / ask_AB, bid_BC, bid_AC, (1 - fee) ** 3])


def size_from_depth(levels: List[Tuple[float, float]]) -> float:
    """Return the smallest available quantity across depth levels.

    Args:
        levels: A list of ``(price, quantity)`` tuples.

    Returns:
        The minimum quantity among ``levels`` or ``0.0`` if ``levels`` is
        empty.
    """

    if not levels:
        return 0.0

    return min(qty for _, qty in levels)
