"""Order execution orchestration for triangular arbitrage."""

from __future__ import annotations

from typing import Dict

from .triangle import top, net_edge_cycle, size_from_depth
from ..adapters.base import ExchangeAdapter
from ..models import Triangle, OrderSpec


def try_triangle(
    adapter: ExchangeAdapter,
    triangle: Triangle,
    order_books: Dict[str, dict],
    threshold: float,
) -> bool:
    """Attempt to execute a triangular arbitrage cycle.

    The function inspects the provided *order_books* and, if the implied net
    return exceeds *threshold*, submits three linked orders using *adapter*.

    Args:
        adapter: Exchange adapter used for order placement.
        triangle: Trading symbols forming the arbitrage path.
        order_books: Mapping of symbol to order book data containing ``bids`` and
            ``asks``.
        threshold: Minimum acceptable net return. Values at or below this level
            cause the trade to be skipped.

    Returns:
        ``True`` if the three orders were submitted, otherwise ``False``.
    """
    try:
        ab = order_books[triangle.leg_ab]
        bc = order_books[triangle.leg_bc]
        ac = order_books[triangle.leg_ac]
    except KeyError:
        return False

    ab_price, ab_qty = top(ab.get("asks", []))
    bc_price, bc_qty = top(bc.get("bids", []))
    ac_price, ac_qty = top(ac.get("bids", []))

    net = net_edge_cycle([1 / ab_price if ab_price else 0.0, bc_price, ac_price])
    if net <= threshold:
        return False

    size = size_from_depth([(ab_price, ab_qty), (bc_price, bc_qty), (ac_price, ac_qty)])
    if size <= 0.0:
        return False

    orders = [
        OrderSpec(symbol=triangle.leg_ab, side="buy", quantity=size, price=ab_price),
        OrderSpec(symbol=triangle.leg_bc, side="sell", quantity=size, price=bc_price),
        OrderSpec(symbol=triangle.leg_ac, side="sell", quantity=size, price=ac_price),
    ]

    for order in orders:
        adapter.create_order(order)

    return True
