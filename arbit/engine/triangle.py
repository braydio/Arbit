"""Utility helpers for triangular arbitrage calculations."""

from __future__ import annotations

from typing import Sequence


def top(book_side: Sequence[tuple[float, float]]) -> tuple[float, float]:
    """Return the top price and quantity for an order book side.

    Args:
        book_side: Sequence of ``(price, quantity)`` tuples ordered best first.

    Returns:
        A tuple ``(price, quantity)`` representing the best available level. If
        *book_side* is empty, ``(0.0, 0.0)`` is returned.
    """
    if book_side:
        return book_side[0]
    return (0.0, 0.0)


def net_edge_cycle(edges: Sequence[float]) -> float:
    """Return the net result for a sequence of exchange rate edges.

    The function multiplies the provided *edges* together and subtracts one,
    yielding the net gain relative to the starting amount.

    Args:
        edges: Iterable of exchange rate multipliers.

    Returns:
        Net profit/loss as a multiplier minus one.
    """
    net = 1.0
    for edge in edges:
        net *= edge
    return net - 1.0


def size_from_depth(levels: Sequence[tuple[float, float]]) -> float:
    """Determine executable quantity based on top-of-book levels.

    The function returns the smallest quantity across all *levels*, representing
    the maximum size that can be traded without exceeding any single level's
    available quantity.

    Args:
        levels: Sequence of ``(price, quantity)`` pairs.

    Returns:
        Maximum trade size permitted by the supplied *levels*. ``0.0`` is
        returned when *levels* is empty.
    """
    if not levels:
        return 0.0
    return min(qty for _, qty in levels)
