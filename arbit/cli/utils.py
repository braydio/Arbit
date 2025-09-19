"""Shared helpers used across Arbit CLI command modules."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from importlib import import_module as _import_module

from arbit.adapters import AlpacaAdapter, CCXTAdapter, ExchangeAdapter
from arbit.config import settings
from arbit.engine.executor import stream_triangles, try_triangle
from arbit.engine.triangle import (
    discover_triangles_from_markets as _discover_triangles_from_markets,
)
from arbit.metrics.exporter import (
    CYCLE_LATENCY,
    FILLS_TOTAL,
    ORDERS_TOTAL,
    PROFIT_TOTAL,
)
from arbit.models import Fill, Triangle, TriangleAttempt
from arbit.notify import fmt_usd, notify_discord
from arbit.persistence.db import init_db, insert_attempt, insert_fill, insert_triangle

AaveProvider = _import_module("arbit.yield").AaveProvider

log = logging.getLogger("arbit")


def format_live_heartbeat(
    venue: str,
    dry_run: bool,
    attempts: int,
    successes: int,
    last_net: float,
    last_pnl: float,
    net_total: float,
    latency_total: float,
    start_time: float,
) -> str:
    """Build a Discord heartbeat summary for live trading."""

    hit_rate = (successes / attempts * 100.0) if attempts else 0.0
    avg_spread = (net_total / successes * 100.0) if successes else 0.0
    avg_latency_ms = (latency_total / attempts * 1000.0) if attempts else 0.0
    elapsed = max(time.time() - start_time, 1e-6)
    attempts_per_sec = attempts / elapsed
    return (
        f"[{venue}] heartbeat: dry_run={dry_run}, attempts={attempts}, "
        f"successes={successes}, hit_rate={hit_rate:.2f}%, "
        f"avg_spread={avg_spread:.2f}%, avg_latency_ms={avg_latency_ms:.1f}, "
        f"last_net={last_net * 100:.2f}%, last_pnl={fmt_usd(last_pnl)} USDT, "
        f"attempts_per_sec={attempts_per_sec:.2f}"
    )


def _triangles_for(venue: str) -> list[Triangle]:
    """Return configured triangles for *venue*, falling back to defaults."""

    data_raw = getattr(settings, "triangles_by_venue", {}) or {}
    data = data_raw
    if isinstance(data_raw, str):
        try:
            import json as _json

            parsed = _json.loads(data_raw)
            if isinstance(parsed, dict):
                data = parsed
            else:
                log.warning(
                    "TRIANGLES_BY_VENUE provided but is not an object; ignoring"
                )
                data = {}
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("failed to parse TRIANGLES_BY_VENUE; using defaults: %s", exc)
            data = {}
    if not isinstance(data, dict):
        data = {}

    triples = data.get(venue)
    if not isinstance(triples, list) or not triples:
        triples = [
            ["ETH/USDT", "ETH/BTC", "BTC/USDT"],
            ["ETH/USDC", "ETH/BTC", "BTC/USDC"],
        ]
    out: list[Triangle] = []
    for t in triples:
        if isinstance(t, (list, tuple)) and len(t) == 3:
            out.append(Triangle(str(t[0]), str(t[1]), str(t[2])))
    return out


def _build_adapter(venue: str, _settings=settings) -> ExchangeAdapter:
    """Factory for constructing exchange adapters."""

    if venue.lower() == "alpaca":
        prefer_native = bool(getattr(_settings, "alpaca_prefer_native", True))
        force_ccxt = str(getattr(_settings, "alpaca_use_ccxt", "")).strip().lower()
        if force_ccxt in {"1", "true", "yes", "on"}:
            prefer_native = False
        if prefer_native and AlpacaAdapter is not None:
            try:
                return AlpacaAdapter()
            except Exception as exc:  # pragma: no cover - adapter construction
                logging.getLogger("arbit").warning(
                    "AlpacaAdapter unavailable (%s); falling back to CCXTAdapter", exc
                )
        return CCXTAdapter(venue)
    return CCXTAdapter(venue)


def _log_balances(venue: str, adapter: ExchangeAdapter) -> None:
    """Log non-zero asset balances for *adapter* at run start."""

    try:
        balances = adapter.balances()
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("%s balance fetch failed: %s", venue, exc)
        return
    if balances:
        bal_str = ", ".join(f"{k}={v}" for k, v in balances.items())
        log.info("%s starting balances %s", venue, bal_str)
    else:
        log.info("%s starting balances none", venue)


def _balances_brief(adapter: ExchangeAdapter, max_items: int = 4) -> str:
    """Return a compact string of non-zero balances for Discord/log lines."""

    try:
        balances = adapter.balances() or {}
    except Exception:  # pragma: no cover - defensive
        return "bal n/a"
    if not balances:
        return "bal none"
    priority = {"USDT": 100, "USDC": 90, "BTC": 80, "ETH": 70}
    items = sorted(
        balances.items(), key=lambda kv: (-(priority.get(kv[0], 0)), -float(kv[1]))
    )[:max_items]
    return "bal " + ", ".join(f"{k}={float(v):.6g}" for k, v in items)


async def _live_run_for_venue(
    venue: str,
    *,
    symbols: str | None = None,
    auto_suggest_top: int = 0,
    attempt_notify_override: bool | None = None,
) -> None:
    """Run the continuous live loop for a single venue (async).

    Notes
    -----
    Per-attempt Discord and console logs include the cumulative attempt
    counter so operators can monitor trading cadence remotely.  When debug
    logging is enabled each skipped triangle additionally records the latest
    per-leg top-of-book snapshot (or a ``"stale"`` marker) to aid diagnosis.
    """

    adapter = _build_adapter(venue, settings)
    _log_balances(venue, adapter)
    conn = init_db(settings.sqlite_path)
    triangles = _triangles_for(venue)
    if symbols:
        allowed = {s.strip() for s in symbols.split(",") if s.strip()}
        if allowed:
            triangles = [
                tri
                for tri in triangles
                if all(leg in allowed for leg in (tri.leg_ab, tri.leg_bc, tri.leg_ac))
            ]
    try:
        markets = adapter.load_markets()
        missing: list[tuple[Triangle, list[str]]] = []
        kept: list[Triangle] = []
        is_alpaca = adapter.name().lower() == "alpaca"
        map_usdt = bool(getattr(settings, "alpaca_map_usdt_to_usd", False))

        def _supported(leg: str) -> bool:
            if leg in markets:
                return True
            if (
                is_alpaca
                and map_usdt
                and isinstance(leg, str)
                and leg.upper().endswith("/USDT")
            ):
                alt = leg[:-5] + "/USD"
                return alt in markets
            return False

        for tri in triangles:
            legs = [tri.leg_ab, tri.leg_bc, tri.leg_ac]
            miss = [leg for leg in legs if not _supported(leg)]
            if miss:
                missing.append((tri, miss))
            else:
                kept.append(tri)
        triangles = kept
    except Exception:
        pass
    if not triangles:
        suggestions: list[list[str]] = []
        try:
            markets = adapter.load_markets()
            suggestions = _discover_triangles_from_markets(markets)[:3]
        except Exception:
            suggestions = []
        use_count = int(auto_suggest_top or 0)
        if use_count > 0 and suggestions:
            chosen = suggestions[:use_count]
            triangles = [Triangle(*t) for t in chosen]
            try:
                notify_discord(
                    venue,
                    (
                        f"[live@{venue}] using auto-suggested triangles for session: "
                        f"{'; '.join('|'.join(t) for t in chosen)} | {_balances_brief(adapter)}"
                    ),
                )
            except Exception:
                pass
        else:
            log.error(
                (
                    "live@%s no supported triangles after filtering; missing=%s "
                    "suggestions=%s"
                ),
                venue,
                (
                    "; ".join(
                        f"{tri.leg_ab}|{tri.leg_bc}|{tri.leg_ac} -> missing {','.join(miss)}"
                        for tri, miss in (missing if "missing" in locals() else [])
                    )
                    if "missing" in locals() and missing
                    else "n/a"
                ),
                ("; ".join("|".join(t) for t in suggestions) if suggestions else "n/a"),
            )
            try:
                notify_discord(
                    venue,
                    (
                        f"[live@{venue}] no supported triangles; "
                        f"suggestions={('; '.join('|'.join(t) for t in suggestions)) if suggestions else 'n/a'}"
                        f" | {_balances_brief(adapter)}"
                    ),
                )
            except Exception:
                pass
            return
    if triangles:
        tri_list = ", ".join(
            f"{tri.leg_ab}|{tri.leg_bc}|{tri.leg_ac}" for tri in triangles
        )
        log.info("live@%s active triangles=%d -> %s", venue, len(triangles), tri_list)
        try:
            notify_discord(
                venue,
                f"[live@{venue}] active triangles={len(triangles)} -> {tri_list} | {_balances_brief(adapter)}",
            )
        except Exception:
            pass
    for tri in triangles:
        try:
            insert_triangle(conn, tri)
        except Exception:
            pass
    log.info("live@%s dry_run=%s", venue, settings.dry_run)
    last_hb_at = time.time()
    last_trade_notify_at = 0.0
    last_attempt_notify_at = 0.0
    min_interval = float(
        getattr(settings, "discord_min_notify_interval_secs", 10.0) or 10.0
    )
    attempt_notify = (
        bool(attempt_notify_override)
        if attempt_notify_override is not None
        else bool(getattr(settings, "discord_attempt_notify", False))
    )
    start_time = time.time()
    attempts_total = 0
    successes_total = 0
    net_total = 0.0
    latency_total = 0.0
    skip_counts: dict[str, int] = {}

    def _top_of_book_for(symbol: str) -> dict[str, float | None | str]:
        """Return the best bid/ask for ``symbol`` as floats where possible."""

        try:
            ob = adapter.fetch_orderbook(symbol, 1) or {}
        except Exception as exc:  # pragma: no cover - defensive logging aid
            return {"error": str(exc)}

        def _best(levels) -> float | None:
            if not levels:
                return None
            level = levels[0]
            if isinstance(level, (list, tuple)) and level:
                try:
                    return float(level[0])
                except (TypeError, ValueError):
                    return None
            if isinstance(level, dict):
                price = level.get("price")
                try:
                    return float(price) if price is not None else None
                except (TypeError, ValueError):
                    return None
            return None

        return {
            "bid": _best(ob.get("bids") or []),
            "ask": _best(ob.get("asks") or []),
        }

    try:
        async for tri, res, reasons, latency in stream_triangles(
            adapter,
            triangles,
            float(getattr(settings, "net_threshold_bps", 0) or 0) / 10000.0,
        ):
            CYCLE_LATENCY.labels(venue).observe(latency)
            attempts_total += 1
            latency_total += float(latency or 0.0)
            if res is None:
                for reason in reasons or ["unknown"]:
                    skip_counts[reason] = skip_counts.get(reason, 0) + 1
                if log.isEnabledFor(logging.DEBUG):
                    stale = "stale_book" in (reasons or [])
                    tob = {}
                    for leg in (tri.leg_ab, tri.leg_bc, tri.leg_ac):
                        if stale:
                            tob[leg] = "stale"
                        else:
                            tob[leg] = _top_of_book_for(leg)
                    log.debug(
                        "live@%s skip attempt#%d %s reasons=%s tob=%s",
                        venue,
                        attempts_total,
                        tri,
                        reasons or ["unknown"],
                        tob,
                    )
                if (
                    attempt_notify
                    and (time.time() - last_attempt_notify_at) > min_interval
                ):
                    try:
                        reason_summary = ",".join(reasons or ["unknown"])[:200]
                        notify_discord(
                            venue,
                            (
                                f"[live@{venue}] attempt#{attempts_total} "
                                f"SKIP {tri} reasons={reason_summary}"
                            ),
                        )
                    except Exception:
                        pass
                    last_attempt_notify_at = time.time()
                continue
            try:
                attempt_id = insert_attempt(
                    conn,
                    TriangleAttempt(
                        ts_iso=datetime.now(timezone.utc).isoformat(),
                        venue=venue,
                        leg_ab=tri.leg_ab,
                        leg_bc=tri.leg_bc,
                        leg_ac=tri.leg_ac,
                        ok=True,
                        net_est=res["net_est"],
                        realized_usdt=res["realized_usdt"],
                        threshold_bps=float(
                            getattr(settings, "net_threshold_bps", 0.0) or 0.0
                        ),
                        notional_usd=float(
                            getattr(settings, "notional_per_trade_usd", 0.0) or 0.0
                        ),
                        slippage_bps=float(
                            getattr(settings, "max_slippage_bps", 0.0) or 0.0
                        ),
                        dry_run=bool(getattr(settings, "dry_run", True)),
                        latency_ms=latency * 1000.0,
                        skip_reasons=None,
                        ab_bid=None,
                        ab_ask=None,
                        bc_bid=None,
                        bc_ask=None,
                        ac_bid=None,
                        ac_ask=None,
                        qty_base=(
                            float(res["fills"][0]["qty"]) if res.get("fills") else None
                        ),
                    ),
                )
            except Exception:
                attempt_id = None
            successes_total += 1
            try:
                net_total += float(res.get("net_est", 0.0) or 0.0)
            except Exception:
                pass
            try:
                PROFIT_TOTAL.labels(venue).set(res["realized_usdt"])
                ORDERS_TOTAL.labels(venue, "ok").inc()
            except Exception:
                pass
            for fill in res.get("fills") or []:
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
                            dry_run=bool(getattr(settings, "dry_run", True)),
                            attempt_id=attempt_id,
                        ),
                    )
                    FILLS_TOTAL.labels(venue).inc()
                except Exception as exc:
                    log.error("persist fill error: %s", exc)
            log.info(
                "%s attempt#%d %s net=%.3f%% (est. profit after fees) PnL=%.2f USDT",
                venue,
                attempts_total,
                tri,
                res["net_est"] * 100,
                res["realized_usdt"],
            )
            if (time.time() - last_trade_notify_at) > min_interval:
                try:
                    qty = (
                        float(res["fills"][0]["qty"])
                        if res and res.get("fills")
                        else None
                    )
                    if attempt_notify:
                        msg = (
                            f"[live@{venue}] attempt#{attempts_total} OK {tri} "
                            f"net={res['net_est'] * 100:.2f}% "
                            f"pnl={res['realized_usdt']:.4f} USDT "
                        )
                        if attempt_id is not None:
                            msg += f"attempt_id={attempt_id} "
                        msg += f"successes_total={successes_total} "
                        if qty is not None:
                            msg += f"qty={qty:.6g} "
                        msg += f"slip_bps={getattr(settings, 'max_slippage_bps', 0)} | {_balances_brief(adapter)}"
                        notify_discord(venue, msg)
                        last_trade_notify_at = time.time()
                    elif bool(getattr(settings, "discord_trade_notify", False)):
                        msg = (
                            f"[{venue}] TRADE attempt#{attempts_total} {tri} "
                            f"net={res['net_est'] * 100:.2f}% "
                            f"pnl={res['realized_usdt']:.4f} USDT "
                        )
                        if attempt_id is not None:
                            msg += f"attempt_id={attempt_id} "
                        msg += f"successes_total={successes_total} "
                        if qty is not None:
                            msg += f"qty={qty:.6g} "
                        msg += f"slip_bps={getattr(settings, 'max_slippage_bps', 0)} | {_balances_brief(adapter)}"
                        notify_discord(venue, msg)
                        last_trade_notify_at = time.time()
                except Exception:
                    pass
            hb_interval = float(
                getattr(settings, "discord_heartbeat_secs", 60.0) or 60.0
            )
            if hb_interval > 0 and time.time() - last_hb_at > hb_interval:
                try:
                    succ_rate = (
                        (successes_total / attempts_total * 100.0)
                        if attempts_total
                        else 0.0
                    )
                    log.info(
                        (
                            "live@%s hb: dry_run=%s attempts=%d successes=%d (%.2f%%) "
                            "last_net=%.2f%% last_pnl=%.4f USDT"
                        ),
                        venue,
                        getattr(settings, "dry_run", True),
                        attempts_total,
                        successes_total,
                        succ_rate,
                        (res["net_est"] * 100.0 if res else 0.0),
                        (res["realized_usdt"] if res else 0.0),
                    )
                    if skip_counts:
                        top = sorted(
                            skip_counts.items(), key=lambda kv: kv[1], reverse=True
                        )[:3]
                        log.info(
                            "live@%s hb: top_skips=%s",
                            venue,
                            ", ".join(f"{k}={v}" for k, v in top),
                        )
                except Exception:
                    pass
                try:
                    notify_discord(
                        venue,
                        format_live_heartbeat(
                            venue,
                            getattr(settings, "dry_run", True),
                            attempts_total,
                            successes_total,
                            res["net_est"] if res else 0.0,
                            res["realized_usdt"] if res else 0.0,
                            net_total,
                            latency_total,
                            start_time,
                        ),
                    )
                except Exception:
                    pass
                last_hb_at = time.time()
    except Exception:
        pass

    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


__all__ = [
    "AaveProvider",
    "AlpacaAdapter",
    "CCXTAdapter",
    "ExchangeAdapter",
    "_balances_brief",
    "_build_adapter",
    "_live_run_for_venue",
    "_log_balances",
    "_triangles_for",
    "format_live_heartbeat",
    "stream_triangles",
    "try_triangle",
]
