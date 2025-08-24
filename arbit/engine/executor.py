from arbit.adapters.base import ExchangeAdapter, OrderSpec
from arbit.engine.triangle import Triangle, top, net_edge, size_from_depth
from arbit.config import settings


def try_tri(adapter: ExchangeAdapter, tri: Triangle):
    obAB = adapter.fetch_orderbook(tri.AB, 10)
    obBC = adapter.fetch_orderbook(tri.BC, 10)
    obAC = adapter.fetch_orderbook(tri.AC, 10)

    bidAB, askAB = top(obAB)
    bidBC, askBC = top(obBC)
    bidAC, askAC = top(obAC)
    if None in (bidAB, askAB, bidBC, askBC, bidAC, askAC):
        return None

    taker = adapter.fetch_fees(tri.AB)[1]
    net = net_edge(askAB, bidBC, bidAC, taker)
    if net < (settings.net_threshold_bps / 10000.0):
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
