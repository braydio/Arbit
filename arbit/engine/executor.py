"""Execution helpers for triangular arbitrage strategies."""

from arbit.adapters.base import ExchangeAdapter, OrderSpec
from arbit.engine.triangle import Triangle, top, net_edge, size_from_depth
from arbit.config import settings


def try_tri(adapter: ExchangeAdapter, tri: Triangle):
    """Attempt to execute a triangular arbitrage cycle.

    Args:
        adapter: Exchange interface used for market data and order placement.
        tri:     The trading triangle to evaluate.

    Returns:
        A dictionary with fill information when profitable, otherwise ``None``.
    """

    obAB = adapter.fetch_orderbook(tri.AB, 10)
    obBC = adapter.fetch_orderbook(tri.BC, 10)
    obAC = adapter.fetch_orderbook(tri.AC, 10)

    levelsAB = [(b[0], a[0]) for b, a in zip(obAB.get("bids", []), obAB.get("asks", []))]
    levelsBC = [(b[0], a[0]) for b, a in zip(obBC.get("bids", []), obBC.get("asks", []))]
    levelsAC = [(b[0], a[0]) for b, a in zip(obAC.get("bids", []), obAC.get("asks", []))]

    bidAB, askAB = top(levelsAB)
    bidBC, askBC = top(levelsBC)
    bidAC, askAC = top(levelsAC)
    if None in (bidAB, askAB, bidBC, askBC, bidAC, askAC):
        return None

    taker = adapter.fetch_fees(tri.AB)[1]
    net = net_edge(askAB, bidBC, bidAC, taker)
    if net < (settings.net_threshold_bps / 10000.0):
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
