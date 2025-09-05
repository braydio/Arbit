"""Utilities for executing triangular arbitrage cycles."""

import time
from typing import AsyncGenerator, Iterable

from arbit.adapters.base import ExchangeAdapter, OrderSpec
from arbit.config import settings
from arbit.engine.triangle import net_edge, size_from_depth, top
from arbit.models import Triangle


def try_triangle(
    adapter: ExchangeAdapter,
    tri: Triangle,
    books: dict,
    threshold: float,
    skip_reasons: list[str] | None = None,
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

    obAB = books.get(tri.leg_ab, {"bids": [], "asks": []})
    obBC = books.get(tri.leg_bc, {"bids": [], "asks": []})
    obAC = books.get(tri.leg_ac, {"bids": [], "asks": []})

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
        if skip_reasons is not None:
            skip_reasons.append("incomplete_book")
        return None

    taker = adapter.fetch_fees(tri.leg_ab)[1]
    net = net_edge(askAB, bidBC, bidAC, taker)
    if net < threshold:
        if skip_reasons is not None:
            skip_reasons.append("below_threshold")
        return None

    # Determine executable size from top-of-book depth
    ask_price = obAB["asks"][0][0]
    qtyB = size_from_depth([obAB["asks"][0], obBC["bids"][0], obAC["bids"][0]])

    # Enforce per-trade notional cap using AB quote currency price
    # If AB is quoted in a stablecoin (USDT/USDC), limit quantity accordingly
    try:
        max_notional = float(getattr(settings, "notional_per_trade_usd", 0.0))
    except Exception:
        max_notional = 0.0
    if max_notional and ask_price > 0:
        max_qty_by_notional = max_notional / ask_price
        qtyB = min(qtyB, max_qty_by_notional)
        if qtyB <= 0:
            if skip_reasons is not None:
                skip_reasons.append("notional_cap")
            return None

    # Enforce exchange min-notional for AB leg
    try:
        min_cost_ab = float(adapter.min_notional(tri.leg_ab))
    except Exception:
        min_cost_ab = 0.0
    if min_cost_ab > 0 and ask_price > 0:
        min_qty_ab = min_cost_ab / ask_price
        if qtyB < min_qty_ab:
            if skip_reasons is not None:
                skip_reasons.append("min_notional_ab")
            return None

    # Simple slippage guard before placing AB order
    slip_frac = max(float(getattr(settings, "max_slippage_bps", 0)) / 10000.0, 0.0)
    if slip_frac > 0:
        obAB_now = adapter.fetch_orderbook(tri.leg_ab, 1)
        ask_now = obAB_now.get("asks", [[ask_price]])[0][0]
        if ask_price > 0 and (ask_now - ask_price) / ask_price > slip_frac:
            if skip_reasons is not None:
                skip_reasons.append("slippage_ab")
            return None
    qtyB = min(qtyB, settings.notional_per_trade_usd / ask_price)
    try:
        min_cost_ab2 = float(adapter.min_notional(tri.leg_ab))
    except Exception:
        min_cost_ab2 = 0.0
    if (qtyB * ask_price) < min_cost_ab2:
        if skip_reasons is not None:
            skip_reasons.append("min_notional_ab")
        return None

    # Three IOC market legs
    f1 = adapter.create_order(OrderSpec(tri.leg_ab, "buy", qtyB, "IOC", "market"))
    try:
        fee_rate_ab = adapter.fetch_fees(tri.leg_ab)[1]
    except Exception:
        fee_rate_ab = None
    f1.update({"leg": "AB", "fee_rate": fee_rate_ab, "tif": "IOC", "type": "market"})
    # Slippage + min-notional check for BC leg
    obBC_now = adapter.fetch_orderbook(tri.leg_bc, 1)
    bidBC_now = obBC_now.get("bids", [[bidBC]])[0][0]
    if slip_frac > 0 and bidBC > 0 and (bidBC - bidBC_now) / bidBC > slip_frac:
        if skip_reasons is not None:
            skip_reasons.append("slippage_bc")
        return None
    try:
        min_cost_bc = float(adapter.min_notional(tri.leg_bc))
    except Exception:
        min_cost_bc = 0.0
    if min_cost_bc > 0 and bidBC_now > 0:
        # cost = price * amount in quote currency
        if qtyB * bidBC_now < min_cost_bc:
            if skip_reasons is not None:
                skip_reasons.append("min_notional_bc")
            return None
    f2 = adapter.create_order(OrderSpec(tri.leg_bc, "sell", qtyB, "IOC", "market"))
    try:
        fee_rate_bc = adapter.fetch_fees(tri.leg_bc)[1]
    except Exception:
        fee_rate_bc = None
    f2.update({"leg": "BC", "fee_rate": fee_rate_bc, "tif": "IOC", "type": "market"})
    qtyC_est = qtyB * bidBC
    # Slippage + min-notional check for AC leg
    obAC_now = adapter.fetch_orderbook(tri.leg_ac, 1)
    bidAC_now = obAC_now.get("bids", [[bidAC]])[0][0]
    if slip_frac > 0 and bidAC > 0 and (bidAC - bidAC_now) / bidAC > slip_frac:
        if skip_reasons is not None:
            skip_reasons.append("slippage_ac")
        return None
    try:
        min_cost_ac = float(adapter.min_notional(tri.leg_ac))
    except Exception:
        min_cost_ac = 0.0
    if min_cost_ac > 0 and bidAC_now > 0:
        if qtyC_est * bidAC_now < min_cost_ac:
            if skip_reasons is not None:
                skip_reasons.append("min_notional_ac")
            return None
    f3 = adapter.create_order(OrderSpec(tri.leg_ac, "sell", qtyC_est, "IOC", "market"))
    try:
        fee_rate_ac = adapter.fetch_fees(tri.leg_ac)[1]
    except Exception:
        fee_rate_ac = None
    f3.update({"leg": "AC", "fee_rate": fee_rate_ac, "tif": "IOC", "type": "market"})

    usdt_out = f1["price"] * f1["qty"] + f1["fee"]
    usdt_in = f3["price"] * f3["qty"] - f3["fee"]
    realized = usdt_in - usdt_out

    return {
        "tri": tri,
        "net_est": net,
        "fills": [f1, f2, f3],
        "realized_usdt": realized,
    }


async def stream_triangles(
    adapter: ExchangeAdapter,
    tris: Iterable[Triangle],
    threshold: float,
    depth: int = 10,
) -> AsyncGenerator[tuple[Triangle, dict | None, list[str], float], None]:
    """Yield arbitrage attempts driven by streaming order book updates.

    This helper maintains an internal cache of the latest order book for each
    symbol referenced by ``tris``.  Whenever all three legs of a triangle have
    fresh data an attempt is made via :func:`try_triangle`.  The function yields
    tuples of ``(triangle, result, skip_reasons, latency)`` where ``result`` is
    the return value from :func:`try_triangle`.
    """

    syms = {s for t in tris for s in (t.leg_ab, t.leg_bc, t.leg_ac)}
    books: dict[str, dict] = {}
    async for sym, ob in adapter.orderbook_stream(syms, depth):
        books[sym] = ob
        for tri in tris:
            legs = (tri.leg_ab, tri.leg_bc, tri.leg_ac)
            if all(b in books for b in legs):
                t0 = time.time()
                res = try_triangle(
                    adapter,
                    tri,
                    {s: books[s] for s in legs},
                    threshold,
                    skip_reasons := [],
                )
                latency = max(time.time() - t0, 0.0)
                yield tri, res, skip_reasons, latency
