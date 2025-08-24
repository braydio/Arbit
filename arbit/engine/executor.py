"""Utilities for executing triangular arbitrage cycles."""

from arbit.adapters.base import ExchangeAdapter, OrderSpec
from arbit.config import settings
from arbit.engine.triangle import Triangle, net_edge, size_from_depth, top


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

    levelsAB = [
        (b[0], a[0]) for b, a in zip(obAB.get("bids", []), obAB.get("asks", []))
    ]
    levelsBC = [
        (b[0], a[0]) for b, a in zip(obBC.get("bids", []), obBC.get("asks", []))
    ]
    levelsAC = [
        (b[0], a[0]) for b, a in zip(obAC.get("bids", []), obAC.get("asks", []))
    ]

    bidAB, askAB = top(levelsAB)
    bidBC, askBC = top(levelsBC)
    bidAC, askAC = top(levelsAC)
    if None in (bidAB, askAB, bidBC, askBC, bidAC, askAC):
        return None

    taker = adapter.fetch_fees(tri.AB)[1]
    net = net_edge(askAB, bidBC, bidAC, taker)
    if net < threshold:
        return None

    ask_price, ask_qty = obAB["asks"][0]
    qtyB = size_from_depth([obAB["asks"][0], obBC["bids"][0], obAC["bids"][0]])
    qtyB = min(qtyB, settings.notional_per_trade_usd / ask_price)
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
