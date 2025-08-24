"""Utilities for executing triangular arbitrage cycles."""

from arbit.adapters.base import ExchangeAdapter, OrderSpec
from arbit.engine.triangle import Triangle, top, net_edge, size_from_depth
from arbit.config import settings


def try_triangle(
    adapter: ExchangeAdapter,
    tri: Triangle,
    books: dict,
    threshold: float,
):
    """Attempt to execute a triangular arbitrage cycle.

    Parameters
    ----------
    adapter:
        Exchange adapter used for order and fee operations.
    tri:
        Triangle describing the market symbols to trade.
    books:
        Mapping of symbol to order book used for pricing.
    threshold:
        Minimum net profit fraction required to execute.
    """

    obAB = books.get(tri.AB, {"bids": [], "asks": []})
    obBC = books.get(tri.BC, {"bids": [], "asks": []})
    obAC = books.get(tri.AC, {"bids": [], "asks": []})

    bidAB, askAB = top(obAB)
    bidBC, askBC = top(obBC)
    bidAC, askAC = top(obAC)
    if None in (bidAB, askAB, bidBC, askBC, bidAC, askAC):
        return None

    taker = adapter.fetch_fees(tri.AB)[1]
    net = net_edge(askAB, bidBC, bidAC, taker)
    if net < threshold:
        return None

    ask_price, ask_qty = obAB["asks"][0]
    qtyB = size_from_depth(settings.notional_per_trade_usd, ask_price, ask_qty)
    if (qtyB * ask_price) < adapter.min_notional(tri.AB):
        return None

    # Three IOC market legs
    f1 = adapter.create_order(OrderSpec(tri.AB, "buy", qtyB, "IOC", "market"))
    f2 = adapter.create_order(OrderSpec(tri.BC, "sell", qtyB, "IOC", "market"))
    qtyC_est = qtyB * bidBC
    f3 = adapter.create_order(OrderSpec(tri.AC, "sell", qtyC_est, "IOC", "market"))

    usdt_out = f1["price"] * f1["qty"] + f1["fee"]
    usdt_in = f3["price"] * f3["qty"] - f3["fee"]
    realized = usdt_in - usdt_out

    return {
        "tri": tri,
        "net_est": net,
        "fills": [f1, f2, f3],
        "realized_usdt": realized,
    }
