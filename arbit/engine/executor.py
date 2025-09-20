"""Utilities for executing triangular arbitrage cycles."""

import logging
import time
from typing import AsyncGenerator, Iterable

from arbit.adapters.base import ExchangeAdapter, OrderSpec
from arbit.config import settings
from arbit.engine.triangle import net_edge_cycle, size_from_depth
from arbit.models import Triangle


log = logging.getLogger(__name__)


def try_triangle(
    adapter: ExchangeAdapter,
    tri: Triangle,
    books: dict,
    threshold: float,
    skip_reasons: list[str] | None = None,
    skip_meta: dict[str, object] | None = None,
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
    skip_reasons:
        Optional list to record skip reasons for diagnostics.
    skip_meta:
        Optional mapping populated when a skip occurs. The mapping captures the
        estimated net edge (if available), top-of-book pricing context, and any
        auxiliary values provided by the skip branch to help downstream
        consumers persist richer attempt metadata.

    Notes
    -----
    Available balance is reduced by ``Settings.reserve_amount_usd`` or
    ``Settings.reserve_percent`` before sizing trades so that funds are held in
    reserve.  When debug logging is enabled every skip path emits a diagnostic
    entry capturing top-of-book prices, the computed net edge (if available),
    and the accumulated skip reasons.
    """

    obAB = books.get(tri.leg_ab, {"bids": [], "asks": []})
    obBC = books.get(tri.leg_bc, {"bids": [], "asks": []})
    obAC = books.get(tri.leg_ac, {"bids": [], "asks": []})

    asks_ab = obAB.get("asks", []) or []
    bids_bc = obBC.get("bids", []) or []
    bids_ac = obAC.get("bids", []) or []

    ask_level_ab = asks_ab[0] if asks_ab else None
    bid_level_bc = bids_bc[0] if bids_bc else None
    bid_level_ac = bids_ac[0] if bids_ac else None

    def _price_from_level(level):
        if level is None:
            return None
        if isinstance(level, (list, tuple)) and level:
            try:
                return float(level[0])
            except (TypeError, ValueError):
                return None
        if isinstance(level, dict):
            price = level.get("price")
            if price is None:
                return None
            try:
                return float(price)
            except (TypeError, ValueError):
                return None
        return None

    askAB = _price_from_level(ask_level_ab)
    bidBC = _price_from_level(bid_level_bc)
    bidAC = _price_from_level(bid_level_ac)

    net_estimate: float | None = None

    def _record_skip(reason: str, **extra) -> None:
        """Append *reason* to ``skip_reasons`` and emit debug diagnostics."""

        if skip_reasons is not None:
            skip_reasons.append(reason)
            reasons_snapshot = list(skip_reasons)
        else:
            reasons_snapshot = [reason]
        if skip_meta is not None:
            skip_meta["reasons"] = reasons_snapshot
            skip_meta["triangle"] = f"{tri.leg_ab}|{tri.leg_bc}|{tri.leg_ac}"
            if net_estimate is not None:
                skip_meta["net_est"] = net_estimate
            skip_meta["prices"] = {
                "ab_ask": askAB,
                "bc_bid": bidBC,
                "ac_bid": bidAC,
            }
            if extra:
                extra_store = skip_meta.setdefault("details", {})
                if isinstance(extra_store, dict):
                    extra_store.update(extra)
        if log.isEnabledFor(logging.DEBUG):
            payload: dict[str, object] = {
                "triangle": f"{tri.leg_ab}|{tri.leg_bc}|{tri.leg_ac}",
                "reasons": reasons_snapshot,
                "net_est": net_estimate,
                "prices": {
                    "ab_ask": askAB,
                    "bc_bid": bidBC,
                    "ac_bid": bidAC,
                },
            }
            if extra:
                payload["extra"] = extra
            log.debug("try_triangle skip %s", payload)
        return None

    if None in (askAB, bidBC, bidAC):
        return _record_skip("incomplete_book")

    # Use per-leg taker fees for a more accurate net estimate
    try:
        fee_ab = float(adapter.fetch_fees(tri.leg_ab)[1])
    except Exception:
        fee_ab = 0.001
    try:
        fee_bc = float(adapter.fetch_fees(tri.leg_bc)[1])
    except Exception:
        fee_bc = fee_ab
    try:
        fee_ac = float(adapter.fetch_fees(tri.leg_ac)[1])
    except Exception:
        fee_ac = fee_ab
    net = net_edge_cycle(
        [1.0 / askAB, bidBC, bidAC, (1 - fee_ab), (1 - fee_bc), (1 - fee_ac)]
    )
    net_estimate = net
    if net < threshold:
        return _record_skip("below_threshold", threshold=threshold)

    # Determine executable size from top-of-book depth
    ask_price = askAB
    qty_levels = [
        lvl for lvl in (ask_level_ab, bid_level_bc, bid_level_ac) if lvl is not None
    ]
    qtyB = size_from_depth(qty_levels)

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
            if skip_meta is not None:
                skip_meta["qty_base_est"] = qtyB
            return _record_skip(
                "notional_cap", max_notional=max_notional, ask_price=ask_price
            )

    # Enforce account reserve so a portion of balance is held back
    quote = tri.leg_ab.split("/")[1]
    available = None
    if hasattr(adapter, "fetch_balance"):
        try:
            bal = float(adapter.fetch_balance(quote))
            reserve = float(getattr(settings, "reserve_amount_usd", 0.0))
            pct = float(getattr(settings, "reserve_percent", 0.0))
            if pct > 0:
                reserve = max(reserve, bal * pct / 100.0)
            available = max(bal - reserve, 0.0)
        except Exception:
            available = None
    if available is not None and ask_price > 0:
        max_qty_by_balance = available / ask_price
        qtyB = min(qtyB, max_qty_by_balance)
        if qtyB <= 0:
            if skip_meta is not None:
                skip_meta["qty_base_est"] = qtyB
            return _record_skip(
                "reserve",
                available=available,
                reserve_amount=float(getattr(settings, "reserve_amount_usd", 0.0)),
            )

    # Enforce exchange min-notional for AB leg
    try:
        min_cost_ab = float(adapter.min_notional(tri.leg_ab))
    except Exception:
        min_cost_ab = 0.0
    if min_cost_ab > 0 and ask_price > 0:
        min_qty_ab = min_cost_ab / ask_price
        if qtyB < min_qty_ab:
            if skip_meta is not None:
                skip_meta["qty_base_est"] = qtyB
            return _record_skip(
                "min_notional_ab", min_cost=min_cost_ab, ask_price=ask_price
            )

    # Simple slippage guard before placing AB order
    slip_frac = max(float(getattr(settings, "max_slippage_bps", 0)) / 10000.0, 0.0)
    if slip_frac > 0:
        obAB_now = adapter.fetch_orderbook(tri.leg_ab, 1)
        ask_now = obAB_now.get("asks", [[ask_price]])[0][0]
        if ask_price > 0 and (ask_now - ask_price) / ask_price > slip_frac:
            if skip_meta is not None:
                skip_meta["qty_base_est"] = qtyB
            return _record_skip(
                "slippage_ab", ask_now=ask_now, ask_price=ask_price, slip_frac=slip_frac
            )
    try:
        min_cost_ab2 = float(adapter.min_notional(tri.leg_ab))
    except Exception:
        min_cost_ab2 = 0.0
    if (qtyB * ask_price) < min_cost_ab2:
        return _record_skip(
            "min_notional_ab", min_cost=min_cost_ab2, ask_price=ask_price
        )

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
        if skip_meta is not None:
            skip_meta["qty_base_est"] = qtyB
        return _record_skip(
            "slippage_bc", bid_now=bidBC_now, bid_then=bidBC, slip_frac=slip_frac
        )
    try:
        min_cost_bc = float(adapter.min_notional(tri.leg_bc))
    except Exception:
        min_cost_bc = 0.0
    if min_cost_bc > 0 and bidBC_now > 0:
        # cost = price * amount in quote currency
        if qtyB * bidBC_now < min_cost_bc:
            if skip_meta is not None:
                skip_meta["qty_base_est"] = qtyB
            return _record_skip(
                "min_notional_bc", min_cost=min_cost_bc, bid_price=bidBC_now
            )
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
        if skip_meta is not None:
            skip_meta["qty_base_est"] = qtyB
            skip_meta["qty_quote_est"] = qtyC_est
        return _record_skip(
            "slippage_ac", bid_now=bidAC_now, bid_then=bidAC, slip_frac=slip_frac
        )
    try:
        min_cost_ac = float(adapter.min_notional(tri.leg_ac))
    except Exception:
        min_cost_ac = 0.0
    if min_cost_ac > 0 and bidAC_now > 0:
        if qtyC_est * bidAC_now < min_cost_ac:
            if skip_meta is not None:
                skip_meta["qty_base_est"] = qtyB
                skip_meta["qty_quote_est"] = qtyC_est
            return _record_skip(
                "min_notional_ac", min_cost=min_cost_ac, bid_price=bidAC_now
            )
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
) -> AsyncGenerator[tuple[Triangle, dict | None, list[str], float, dict[str, object]], None]:
    """Yield arbitrage attempts driven by streaming order book updates.

    This helper maintains an internal cache of the latest order book for each
    symbol referenced by ``tris``.  Whenever all three legs of a triangle have
    fresh data an attempt is made via :func:`try_triangle`.  The function yields
    tuples of ``(triangle, result, skip_reasons, latency, skip_meta)`` where
    ``result`` is the return value from :func:`try_triangle` and ``skip_meta``
    captures any metadata recorded during skip paths (for example estimated net
    edge and pricing context).
    """

    syms = {s for t in tris for s in (t.leg_ab, t.leg_bc, t.leg_ac)}
    books: dict[str, dict] = {}
    seen_at: dict[str, float] = {}
    last_refreshed: dict[str, float] = {}
    max_age_sec = max(
        float(getattr(settings, "max_book_age_ms", 1500) or 1500) / 1000.0, 0.0
    )
    async for sym, ob in adapter.orderbook_stream(syms, depth):
        books[sym] = ob
        seen_at[sym] = time.time()
        for tri in tris:
            legs = (tri.leg_ab, tri.leg_bc, tri.leg_ac)
            if all(b in books for b in legs):
                # Staleness guard across the three legs with optional refresh
                now = time.time()
                stale_syms = [
                    s for s in legs if (now - float(seen_at.get(s, 0.0))) > max_age_sec
                ]
                if stale_syms and max_age_sec > 0.0:
                    if bool(getattr(settings, "refresh_on_stale", True)):
                        # Try a quick REST refresh for stale legs (depth=1), rate-limited
                        min_gap = max(
                            float(
                                getattr(settings, "stale_refresh_min_gap_ms", 150)
                                or 150
                            )
                            / 1000.0,
                            0.0,
                        )
                        for s in stale_syms:
                            last = float(last_refreshed.get(s, 0.0))
                            if (now - last) < min_gap:
                                continue
                            try:
                                ob_s = adapter.fetch_orderbook(s, 1)
                                if (
                                    isinstance(ob_s, dict)
                                    and ob_s.get("bids") is not None
                                ):
                                    books[s] = ob_s
                                    seen_at[s] = time.time()
                            except Exception:
                                pass
                            finally:
                                last_refreshed[s] = time.time()
                        # Recompute staleness after refresh attempts
                        now = time.time()
                        stale_syms = [
                            s
                            for s in legs
                            if (now - float(seen_at.get(s, 0.0))) > max_age_sec
                        ]
                    if stale_syms:
                        yield tri, None, ["stale_book"], 0.0
                        continue
                t0 = time.time()
                skip_reasons: list[str] = []
                skip_meta: dict[str, object] = {}
                try:
                    res = try_triangle(
                        adapter,
                        tri,
                        {s: books[s] for s in legs},
                        threshold,
                        skip_reasons,
                        skip_meta,
                    )
                except Exception:
                    # Defensive: surface as a skip rather than letting background
                    # tasks raise unhandled exceptions that become noisy futures.
                    res = None
                    skip_reasons.append("exec_error")
                latency = max(time.time() - t0, 0.0)
                yield tri, res, skip_reasons, latency, skip_meta
