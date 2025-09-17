"""Fitness sampling CLI commands."""

from __future__ import annotations

import time
from collections import defaultdict
from datetime import datetime, timezone

from arbit.adapters import ExchangeAdapter
from arbit.config import settings
from arbit.models import Fill, Triangle, TriangleAttempt
from arbit.notify import notify_discord
from arbit.persistence.db import init_db, insert_attempt, insert_fill, insert_triangle

from ..core import TyperOption, app, log
from ..utils import try_triangle  # re-exported for compatibility
from ..utils import _build_adapter, _log_balances, _triangles_for


@app.command("fitness")
@app.command("fitness_run")
def fitness(
    venue: str = "alpaca",
    secs: int = 20,
    simulate: bool = False,
    persist: bool = False,
    dummy_trigger: bool = False,
    symbols: str | None = None,
    discord_heartbeat_secs: float = 0.0,
    attempt_notify: bool | None = TyperOption(
        None,
        "--attempt-notify/--no-attempt-notify",
        help="Send per-attempt Discord alerts (noisy). Overrides env.",
    ),
    help_verbose: bool = False,
) -> None:
    """Read-only sanity check that prints bid/ask spreads.

    Notes
    -----
    Discord notifications and CLI logs emitted per attempt now include the
    cumulative attempt counter to help operators correlate simulation
    cadence with downstream metrics.
    """

    if help_verbose:
        app.print_verbose_help_for("fitness")
        raise SystemExit(0)

    adapter = _build_adapter(venue, settings)
    _log_balances(venue, adapter)
    triangles = _triangles_for(venue)
    allowed: set[str] | None = None
    if symbols:
        allowed = {s.strip() for s in symbols.split(",") if s.strip()}
        if allowed:
            triangles = [
                tri
                for tri in triangles
                if all(leg in allowed for leg in (tri.leg_ab, tri.leg_bc, tri.leg_ac))
            ]
    start = time.time()
    symbols_set = {s for tri in triangles for s in (tri.leg_ab, tri.leg_bc, tri.leg_ac)}
    if triangles:
        tri_list = ", ".join(
            f"{tri.leg_ab}|{tri.leg_bc}|{tri.leg_ac}" for tri in triangles
        )
        log.info(
            "fitness@%s active triangles=%d symbols=%d -> %s",
            venue,
            len(triangles),
            len(symbols_set),
            tri_list,
        )

    conn = None
    if simulate and persist:
        conn = init_db(settings.sqlite_path)
        for tri in triangles:
            try:
                insert_triangle(conn, tri)
            except Exception:
                pass

    prev_dry_run = settings.dry_run
    if simulate:
        try:
            settings.dry_run = True
        except Exception:
            pass

    sim_count = 0
    sim_pnl = 0.0
    attempts_total = 0
    skip_counts: dict[str, int] = defaultdict(int)
    loop_idx = 0
    last_hb_at = 0.0
    attempt_notify_flag = (
        bool(attempt_notify)
        if attempt_notify is not None
        else bool(getattr(settings, "discord_attempt_notify", False))
    )
    last_attempt_notify_at = 0.0
    min_interval = float(
        getattr(settings, "discord_min_notify_interval_secs", 10.0) or 10.0
    )
    try:
        while time.time() - start < secs:
            books_cache: dict[str, dict] = {}
            for symbol in symbols_set:
                try:
                    orderbook = adapter.fetch_orderbook(symbol, 5)
                except Exception as exc:
                    log.warning("%s fetch_orderbook skip %s: %s", venue, symbol, exc)
                    continue
                books_cache[symbol] = orderbook
                if orderbook.get("bids") and orderbook.get("asks"):
                    spread = (
                        (orderbook["asks"][0][0] - orderbook["bids"][0][0])
                        / orderbook["asks"][0][0]
                    ) * 1e4
                    log.info(
                        "%s %s spread=%.1f bps (ask-bid gap)", venue, symbol, spread
                    )

            if simulate:
                injected: dict[str, dict] | None = None
                if dummy_trigger and loop_idx == 0 and triangles:
                    tri0 = triangles[0]
                    ask_ab = 100.0
                    bid_bc = 1.01
                    bid_ac = 100.7
                    qty = 1.5
                    injected = {
                        tri0.leg_ab: {
                            "bids": [[ask_ab * 0.999, qty]],
                            "asks": [[ask_ab, qty]],
                        },
                        tri0.leg_bc: {
                            "bids": [[bid_bc, qty]],
                            "asks": [[bid_bc * 1.001, qty]],
                        },
                        tri0.leg_ac: {
                            "bids": [[bid_ac, qty]],
                            "asks": [[bid_ac * 1.001, qty]],
                        },
                    }
                    books_cache.update(injected)
                    try:
                        notify_discord(
                            venue,
                            f"[{venue}] dummy_trigger: injected synthetic profitable triangle {tri0}",
                        )
                    except Exception:
                        pass

                for tri in triangles:
                    skip_reasons: list[str] = []
                    try:
                        t_start = time.time()
                        if injected and tri.leg_ab in injected:
                            original_fetch = adapter.fetch_orderbook

                            def _patched_fetch(sym: str, depth: int = 1):
                                if depth == 1 and sym in injected:
                                    ob = injected[sym]
                                    return {
                                        "bids": [ob["bids"][0]],
                                        "asks": [ob["asks"][0]],
                                    }
                                return original_fetch(sym, depth)

                            adapter.fetch_orderbook = _patched_fetch  # type: ignore[assignment]

                        attempts_total += 1
                        result = try_triangle(
                            adapter,
                            tri,
                            books_cache,
                            settings.net_threshold_bps / 10000.0,
                            skip_reasons,
                        )
                    except Exception as exc:  # pragma: no cover - defensive
                        log.error("simulate error for %s: %s", tri, exc)
                        continue
                    finally:
                        if injected and tri.leg_ab in injected:
                            adapter.fetch_orderbook = original_fetch  # type: ignore[assignment]

                    if conn is not None:

                        def _best(ob, side):
                            try:
                                arr = ob.get(side) or []
                                return arr[0][0] if arr else None
                            except Exception:
                                return None

                        ob_ab = books_cache.get(tri.leg_ab, {})
                        ob_bc = books_cache.get(tri.leg_bc, {})
                        ob_ac = books_cache.get(tri.leg_ac, {})
                        latency_ms = (time.time() - t_start) * 1000.0
                        ok = bool(result)
                        net_est = float(result.get("net_est", 0.0)) if result else None
                        realized = (
                            float(result.get("realized_usdt", 0.0)) if result else None
                        )
                        qty_base = None
                        if result and result.get("fills"):
                            try:
                                qty_base = float(result["fills"][0]["qty"])
                            except Exception:
                                qty_base = None
                        attempt = TriangleAttempt(
                            venue=venue,
                            leg_ab=tri.leg_ab,
                            leg_bc=tri.leg_bc,
                            leg_ac=tri.leg_ac,
                            ts_iso=datetime.now(timezone.utc).isoformat(),
                            ok=ok,
                            net_est=net_est,
                            realized_usdt=realized,
                            threshold_bps=float(
                                getattr(settings, "net_threshold_bps", 0.0)
                            ),
                            notional_usd=float(
                                getattr(settings, "notional_per_trade_usd", 0.0)
                            ),
                            slippage_bps=float(
                                getattr(settings, "max_slippage_bps", 0.0)
                            ),
                            dry_run=True,
                            latency_ms=latency_ms,
                            skip_reasons=(
                                ",".join(skip_reasons) if skip_reasons else None
                            ),
                            ab_bid=_best(ob_ab, "bids"),
                            ab_ask=_best(ob_ab, "asks"),
                            bc_bid=_best(ob_bc, "bids"),
                            bc_ask=_best(ob_bc, "asks"),
                            ac_bid=_best(ob_ac, "bids"),
                            ac_ask=_best(ob_ac, "asks"),
                            qty_base=qty_base,
                        )
                        attempt_id = insert_attempt(conn, attempt)
                    else:
                        attempt_id = None

                    if not result:
                        if skip_reasons:
                            for reason in skip_reasons:
                                skip_counts[reason] = skip_counts.get(reason, 0) + 1
                            if (
                                attempt_notify_flag
                                and (time.time() - last_attempt_notify_at)
                                > min_interval
                            ):
                                try:
                                    reasons_summary = ",".join(
                                        skip_reasons or ["unknown"]
                                    )[:200]
                                    notify_discord(
                                        venue,
                                        (
                                            f"[fitness@{venue}] attempt#{attempts_total} "
                                            f"SKIP {tri} reasons={reasons_summary}"
                                        ),
                                    )
                                except Exception:
                                    pass
                                last_attempt_notify_at = time.time()
                        else:
                            skip_counts["unprofitable"] = (
                                skip_counts.get("unprofitable", 0) + 1
                            )
                        continue

                    sim_count += 1
                    sim_pnl += float(result.get("realized_usdt", 0.0))
                    if (
                        attempt_notify_flag
                        and (time.time() - last_attempt_notify_at) > min_interval
                    ):
                        try:
                            qty = (
                                float(result["fills"][0]["qty"])
                                if result and result.get("fills")
                                else None
                            )
                            msg = (
                                f"[fitness@{venue}] attempt#{attempts_total} OK {tri} "
                                f"net={result['net_est'] * 100:.2f}% "
                                f"pnl={result['realized_usdt']:.4f} USDT "
                                f"sim_trades_total={sim_count} "
                            )
                            if qty is not None:
                                msg += f"qty={qty:.6g} "
                            msg += (
                                f"slip_bps={getattr(settings, 'max_slippage_bps', 0)}"
                            )
                            notify_discord(venue, msg)
                        except Exception:
                            pass
                        last_attempt_notify_at = time.time()
                    for fill in result.get("fills", []):
                        if conn is not None:
                            try:
                                insert_fill(
                                    conn,
                                    Fill(
                                        order_id=str(fill.get("id", "")),
                                        symbol=str(fill.get("symbol", "")),
                                        side=str(fill.get("side", "")),
                                        price=float(fill.get("price", 0.0)),
                                        quantity=float(fill.get("qty", 0.0)),
                                        fee=float(fill.get("fee", 0.0)),
                                        timestamp=None,
                                        venue=venue,
                                        leg=str(fill.get("leg") or ""),
                                        tif=str(fill.get("tif") or ""),
                                        order_type=str(fill.get("type") or ""),
                                        fee_rate=(
                                            float(fill.get("fee_rate"))
                                            if fill.get("fee_rate") is not None
                                            else None
                                        ),
                                        notional=float(fill.get("price", 0.0))
                                        * float(fill.get("qty", 0.0)),
                                        dry_run=True,
                                        attempt_id=(
                                            attempt_id
                                            if "attempt_id" in locals()
                                            else None
                                        ),
                                    ),
                                )
                            except Exception:
                                pass
                    log.info(
                        "%s [sim] attempt#%d %s net=%.3f%% PnL=%.2f USDT",
                        venue,
                        attempts_total,
                        tri,
                        result.get("net_est", 0.0) * 100.0,
                        result.get("realized_usdt", 0.0),
                    )
            time.sleep(0.25)
            loop_idx += 1
            if (
                discord_heartbeat_secs
                and discord_heartbeat_secs > 0
                and (time.time() - last_hb_at) > float(discord_heartbeat_secs)
            ):
                try:
                    top = ", ".join(
                        f"{k}={v}"
                        for k, v in sorted(
                            skip_counts.items(), key=lambda kv: kv[1], reverse=True
                        )[:3]
                    )
                    notify_discord(
                        venue,
                        (
                            f"[fitness@{venue}] heartbeat simulate={simulate} symbols={len(symbols_set)} "
                            f"attempts={attempts_total} sim_trades={sim_count} "
                            f"sim_total_pnl={sim_pnl:.2f} USDT top_skips={top or 'n/a'}"
                        ),
                    )
                except Exception:
                    pass
                last_hb_at = time.time()
    finally:
        if simulate:
            try:
                settings.dry_run = prev_dry_run
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    if simulate:
        log.info(
            "%s [sim] summary: attempts=%d trades=%d total_pnl=%.2f USDT",
            venue,
            attempts_total,
            sim_count,
            sim_pnl,
        )
    try:
        top = ", ".join(
            f"{k}={v}"
            for k, v in sorted(skip_counts.items(), key=lambda kv: kv[1], reverse=True)[
                :3
            ]
        )
        notify_discord(
            venue,
            (
                f"[fitness@{venue}] summary simulate={simulate} attempts={attempts_total} "
                f"trades={sim_count} pnl={sim_pnl:.2f} USDT top_skips={top or 'n/a'}"
            ),
        )
    except Exception:
        pass


@app.command("hybrid")
def fitness_hybrid(
    legs: str = "ETH/USDT,ETH/BTC,BTC/USDT",
    venues: str | None = None,
    secs: int = 10,
) -> None:
    """Read-only multi-venue net% estimate using per-leg venue mapping."""

    def _parse_csv(s: str | None) -> list[str]:
        if not s:
            return []
        return [item.strip() for item in s.split(",") if item.strip()]

    def _parse_map(s: str | None) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for item in _parse_csv(s):
            if "=" in item:
                sym, ven = item.split("=", 1)
                sym = sym.strip()
                ven = ven.strip()
                if sym and ven:
                    mapping[sym] = ven
        return mapping

    legs_list = _parse_csv(legs)
    if len(legs_list) != 3:
        log.error("--legs must provide exactly three symbols (AB,BC,AC)")
        raise SystemExit(2)
    leg_ab, leg_bc, leg_ac = legs_list
    venue_map = _parse_map(venues)
    used_venues = {
        venue_map.get(leg_ab, ""),
        venue_map.get(leg_bc, ""),
        venue_map.get(leg_ac, ""),
    }
    used_venues = {v for v in used_venues if v}

    adapters: dict[str, ExchangeAdapter] = {}
    for venue_name in used_venues or {"kraken"}:
        adapters[venue_name] = _build_adapter(venue_name, settings)

    def _best(ob: dict) -> tuple[float | None, float | None]:
        try:
            bid = ob.get("bids", [[None]])[0][0]
        except Exception:
            bid = None
        try:
            ask = ob.get("asks", [[None]])[0][0]
        except Exception:
            ask = None
        return bid, ask

    def _taker(venue_name: str, symbol: str) -> float:
        try:
            return adapters[venue_name].fetch_fees(symbol)[1]
        except Exception:
            return 0.001

    t0 = time.time()
    while time.time() - t0 < secs:
        ven_ab = venue_map.get(leg_ab) or next(iter(adapters))
        ven_bc = venue_map.get(leg_bc) or next(iter(adapters))
        ven_ac = venue_map.get(leg_ac) or next(iter(adapters))
        try:
            ob_ab = adapters[ven_ab].fetch_orderbook(leg_ab, 1)
            ob_bc = adapters[ven_bc].fetch_orderbook(leg_bc, 1)
            ob_ac = adapters[ven_ac].fetch_orderbook(leg_ac, 1)
        except Exception as exc:
            log.warning("fitness:hybrid fetch error: %s", exc)
            time.sleep(1.0)
            continue
        bid_ab, ask_ab = _best(ob_ab)
        bid_bc, ask_bc = _best(ob_bc)
        bid_ac, ask_ac = _best(ob_ac)
        if None in (ask_ab, bid_bc, bid_ac):
            log.info(
                "fitness:hybrid %s@%s %s@%s %s@%s incomplete books",
                leg_ab,
                ven_ab,
                leg_bc,
                ven_bc,
                leg_ac,
                ven_ac,
            )
            time.sleep(1.0)
            continue
        gross = (1.0 / float(ask_ab)) * float(bid_bc) * float(bid_ac)
        f_ab = _taker(ven_ab, leg_ab)
        f_bc = _taker(ven_bc, leg_bc)
        f_ac = _taker(ven_ac, leg_ac)
        net = gross * (1 - f_ab) * (1 - f_bc) * (1 - f_ac) - 1.0
        log.info(
            "fitness:hybrid %s@%s %s@%s %s@%s net=%.3f%% (fees ab/bc/ac=%.1f/%.1f/%.1f bps)",
            leg_ab,
            ven_ab,
            leg_bc,
            ven_bc,
            leg_ac,
            ven_ac,
            net * 100.0,
            f_ab * 1e4,
            f_bc * 1e4,
            f_ac * 1e4,
        )
        time.sleep(1.0)


__all__ = ["fitness", "fitness_hybrid"]
