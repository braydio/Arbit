"""Command line interface utilities.

This module exposes Typer-based commands for interacting with the
arbitrage engine.  Helper functions for metrics and persistence are
imported here so tests can easily monkeypatch them.
"""

import asyncio
import logging
import sys
import time
from datetime import datetime, timezone
from importlib import import_module as _import_module

import typer
# Backward-compat: some environments may lack typer.Option; provide a fallback
try:  # pragma: no cover - environment-specific
    from typer import Option as TyperOption
except Exception:  # pragma: no cover
    def TyperOption(default=None, *args, **kwargs):
        return default
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
    YIELD_ALERTS_TOTAL,
    YIELD_APR,
    YIELD_BEST_APR,
    YIELD_CHECKS_TOTAL,
    YIELD_DEPOSITS_TOTAL,
    YIELD_ERRORS_TOTAL,
    YIELD_WITHDRAWS_TOTAL,
    start_metrics_server,
)
from arbit.models import Fill, Triangle, TriangleAttempt
from arbit.notify import fmt_usd, notify_discord
from arbit.persistence.db import (
    init_db,
    insert_attempt,
    insert_fill,
    insert_triangle,
    insert_yield_op,
)

AaveProvider = _import_module("arbit.yield").AaveProvider


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
    """Build a Discord heartbeat summary for live trading.

    Parameters
    ----------
    venue:
        Exchange venue name.
    dry_run:
        Whether trades are simulated.
    attempts:
        Total triangles evaluated.
    successes:
        Number of profitable hits.
    last_net:
        Net spread fraction from the last attempt.
    last_pnl:
        Realized PnL from the last attempt in USDT.
    net_total:
        Sum of net spreads from successful attempts.
    latency_total:
        Sum of latencies across attempts in seconds.
    start_time:
        Epoch when the loop began.

    Returns
    -------
    str
        Formatted heartbeat message.
    """

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


class CLIApp(typer.Typer):
    """Custom Typer application that prints usage on bad invocation."""

    # ------------------------------------------------------------------
    def _unique_commands(self) -> dict[str, dict[str, object]]:
        """Return mapping of canonical command names to command/aliases."""

        mapping: dict[str, dict[str, object]] = {}
        for name, cmd in self.commands.items():
            canonical = name.replace("_", ":")
            info = mapping.setdefault(canonical, {"command": cmd, "aliases": []})
            info["aliases"].append(name)
        return mapping

    def main(self, args: list[str] | None = None):
        """Run the CLI with *args*, handling help flags and bad input.

        Parameters
        ----------
        args:
            Optional list of command-line arguments.  Defaults to
            ``sys.argv[1:]`` when not provided.

        The method detects ``--help`` and ``--help-verbose`` flags before
        delegating to Typer's normal processing.  ``--help`` prints a short
        summary of available commands while ``--help-verbose`` provides a
        more detailed reference including flags and sample output.
        """

        if args is None:
            args = sys.argv[1:]

        if args and args[0] == "--help-verbose":
            self._print_verbose_help()
            raise SystemExit(0)

        if args and args[0] == "--help":
            self._print_basic_help()
            raise SystemExit(0)

        if not args or args[0] not in self.commands:
            typer.echo("Usage: arbit.cli [COMMAND]")
            if self.commands:
                typer.echo("Commands:")
                for cname in sorted(self._unique_commands()):
                    typer.echo(f"  {cname}")
            raise SystemExit(0 if not args else 1)
        return super().main(args)

    # ------------------------------------------------------------------
    def _print_basic_help(self) -> None:
        """Print a short summary of available commands."""

        typer.echo(
            "Usage: python -m arbit.cli [--help | --help-verbose] COMMAND [ARGS]"
        )
        typer.echo("\nAvailable commands:")
        for cname, info in sorted(self._unique_commands().items()):
            desc = (info["command"].callback.__doc__ or "").strip().splitlines()[0]
            aliases = [
                a.replace("_", ":")
                for a in info["aliases"]
                if a.replace("_", ":") != cname
            ]
            alias_str = f" (aliases: {', '.join(sorted(aliases))})" if aliases else ""
            typer.echo(f"  {cname:<12} {desc}{alias_str}")
        typer.echo("\nTip: run --help-verbose for flags and examples.")

    # ------------------------------------------------------------------
    @staticmethod
    def _print_verbose_help() -> None:
        """Print detailed command reference with flags and examples."""

        typer.echo("Command reference:\n")
        typer.echo("Global: --help (short list), --help-verbose (this view)\n")

        typer.echo(
            "keys:check\n"
            "  Validate exchange credentials by fetching a sample order book.\n"
            "  Aliases: keys:check, keys_check\n"
            "  Sample output:\n"
            "    [alpaca] markets=123 BTC/USDT 60000/60010\n"
        )

        typer.echo(
            "fitness\n"
            "  Monitor order books to gauge spread without trading. Optionally simulate executions.\n"
            "  Flags (all optional):\n"
            "    --venue TEXT              Exchange to query (default: alpaca)\n"
            "    --secs INTEGER            Seconds to run (default: 20)\n"
            "    --simulate/--no-simulate  Try dry-run triangle executions (default: no-simulate)\n"
            "    --persist/--no-persist    Persist simulated fills to SQLite (used with --simulate)\n"
            "    --dummy-trigger           Inject one synthetic profitable triangle (with --simulate)\n"
            "    --help-verbose            Print extra context about fitness output\n"
            "  Sample output:\n"
            "    alpaca ETH/USDT spread=10.0 bps\n"
            "    alpaca [sim] Triangle(ETH/USDT, ETH/BTC, BTC/USDT) net=0.15% PnL=0.05 USDT\n"
        )

        typer.echo(
            "live\n"
            "  Continuously scan for profitable triangles and execute trades.\n"
            "  Flags (optional):\n"
            "    --venue TEXT           Exchange to trade on (default: alpaca)\n"
            "    --symbols TEXT         CSV filter; only triangles whose three legs are all included are traded\n"
            "    --auto-suggest-top INT Use top N discovered triangles if none configured/supported (session only)\n"
            "    --help-verbose         Print extra context about live output semantics\n"
            "  Sample output:\n"
            "    alpaca ETH/BTC net=0.5% PnL=0.10 USDT\n"
        )

        typer.echo(
            "live:multi\n"
            "  Run live loops concurrently across multiple venues.\n"
            "  Aliases: live:multi, live_multi\n"
            "  Flags (optional):\n"
            "    --venues TEXT         CSV of venues (default: settings.exchanges)\n"
            "    --symbols TEXT        CSV filter applied per venue\n"
            "    --auto-suggest-top INT Use top N discovered triangles if none configured/supported\n"
            "  Sample usage:\n"
            "    python -m arbit.cli live:multi --venues alpaca,kraken\n"
        )

        typer.echo(
            "markets:limits\n"
            "  List market min-notional and fees to help size trades.\n"
            "  Aliases: markets:limits, markets_limits\n"
            "  Flags (all optional):\n"
            "    --venue TEXT     Exchange to query (default: alpaca)\n"
            "    --symbols TEXT   CSV filter (e.g., BTC/USDT,ETH/USDT); default = triangle symbols\n"
            "  Sample output:\n"
            "    BTC/USDT min_cost=5.0 maker=10 bps taker=10 bps\n"
        )

        typer.echo(
            "config:recommend\n"
            "  Suggest starter Strategy settings based on venue data.\n"
            "  Aliases: config:recommend, config_recommend\n"
            "  Flags (optional):\n"
            "    --venue TEXT   Exchange to query (default: alpaca)\n"
            "  Sample output:\n"
            "    Recommend: NOTIONAL_PER_TRADE_USD=10 NET_THRESHOLD_BPS=25 MAX_SLIPPAGE_BPS=8 DRY_RUN=true\n"
        )

        typer.echo(
            "fitness:hybrid\n"
            "  Read-only multi-venue check: compute net% using legs sourced from different exchanges.\n"
            "  Aliases: fitness:hybrid, fitness_hybrid\n"
            "  Flags (optional):\n"
            "    --legs TEXT     CSV of legs (default: ETH/USDT,ETH/BTC,BTC/USDT)\n"
            "    --venues TEXT   CSV mapping of symbol=venue (e.g., 'ETH/USDT=kraken,ETH/BTC=kraken,BTC/USDT=alpaca')\n"
            "    --secs INTEGER  Seconds to run sampling (default: 10)\n"
            "  Notes: estimates only; no order placement or simulation across venues.\n"
        )

        typer.echo(
            "config:discover\n"
            "  Discover supported triangles for a venue from load_markets().\n"
            "  Aliases: config:discover, config_discover\n"
            "  Flags (optional):\n"
            "    --venue TEXT     Exchange to query (default: kraken)\n"
            "    --write-env      Write TRIANGLES_BY_VENUE to .env for venue\n"
            "    --env-path TEXT  Path to .env (default: .env)\n"
            "  Sample output:\n"
            "    kraken triangles=15 first=ETH/USDT|ETH/BTC|BTC/USDT\n"
        )

        typer.echo(
            "yield:collect\n"
            "  Deposit idle USDC to Aave v3 to earn yield (beta).\n"
            "  Aliases: yield:collect, yield_collect\n"
            "  Flags (optional):\n"
            "    --asset TEXT        Asset to deposit (default: USDC)\n"
            "    --min-stake INTEGER Minimum token units to deposit (default: settings.min_usdc_stake)\n"
            "    --reserve-usd FLOAT Keep this much USD in wallet (default: settings.reserve_amount_usd; reserve_percent also applied)\n"
            "    --help-verbose      Print extra context and environment requirements\n"
            "  Environment:\n"
            "    RPC_URL, PRIVATE_KEY; USDC/Pool addresses from settings.\n"
            "  Sample output:\n"
            "    [dry-run] would deposit 150.00 USDC to Aave (reserve=50.00)\n"
        )

        typer.echo(
            "yield:watch\n"
            "  Periodically check APR sources and alert if a better yield exists.\n"
            "  Aliases: yield:watch, yield_watch\n"
            "  Flags (optional):\n"
            "    --asset TEXT        Asset symbol (default: USDC)\n"
            "    --sources TEXT      CSV or JSON array of URLs returning {provider, asset, apr_percent}\n"
            "    --interval FLOAT    Poll interval in seconds (default: 60)\n"
            "    --apr-hint FLOAT    Current provider APR used as baseline for alerts\n"
            "    --min-delta-bps INT Minimum APR improvement to alert (default: 50 bps)\n"
            "  Sample output:\n"
            "    Better yield available for USDC: foo 5.10% >= current 4.50% + 0.50%\n"
        )


app = CLIApp()
log = logging.getLogger("arbit")

# Configure logging once with console + optional rotating file handler
if not getattr(log, "_configured", False):
    log.setLevel(getattr(logging, str(settings.log_level).upper(), logging.INFO))
    log.propagate = False
    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(log.level)
    ch.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    log.addHandler(ch)
    # Optional file handler
    try:
        import os
        from logging.handlers import RotatingFileHandler

        log_path = getattr(settings, "log_file", None) or "data/arbit.log"
        if log_path:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            max_bytes = int(getattr(settings, "log_max_bytes", 1_000_000) or 1_000_000)
            backup_count = int(getattr(settings, "log_backup_count", 3) or 3)
            fh = RotatingFileHandler(
                log_path, maxBytes=max_bytes, backupCount=backup_count
            )
            fh.setLevel(log.level)
            fh.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
            )
            log.addHandler(fh)
    except Exception:
        # If file logging fails, continue with console-only
        pass
    setattr(log, "_configured", True)


def _triangles_for(venue: str) -> list[Triangle]:
    data_raw = getattr(settings, "triangles_by_venue", {}) or {}
    data = data_raw
    # Be robust if env provided value as a JSON string or invalid type
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
        except Exception as e:
            log.warning("failed to parse TRIANGLES_BY_VENUE; using defaults: %s", e)
            data = {}
    if not isinstance(data, dict):
        data = {}

    triples = data.get(venue)
    if not isinstance(triples, list) or not triples:
        # Fallback defaults if config missing or tests stub settings
        triples = [
            ["ETH/USDT", "ETH/BTC", "BTC/USDT"],
            ["ETH/USDC", "ETH/BTC", "BTC/USDC"],
        ]
    # Sanitize and coerce to Triangle list
    out: list[Triangle] = []
    for t in triples:
        if isinstance(t, (list, tuple)) and len(t) == 3:
            out.append(Triangle(str(t[0]), str(t[1]), str(t[2])))
    return out


def _build_adapter(venue: str, _settings=settings) -> ExchangeAdapter:
    """Factory for constructing exchange adapters.

    Parameters
    ----------
    venue:
        Exchange identifier understood by the adapter.

    Returns
    -------
    ExchangeAdapter
        ``AlpacaAdapter`` when *venue* is ``"alpaca"`` otherwise
        ``CCXTAdapter``.
    """

    if venue.lower() == "alpaca":
        return AlpacaAdapter()
    return CCXTAdapter(venue)


def _log_balances(venue: str, adapter: ExchangeAdapter) -> None:
    """Log non-zero asset balances for *adapter* at run start.

    Parameters
    ----------
    venue:
        Exchange identifier used for logging context.
    adapter:
        Exchange adapter queried for balances.
    """

    try:
        bals = adapter.balances()
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("%s balance fetch failed: %s", venue, exc)
        return
    if bals:
        bal_str = ", ".join(f"{k}={v}" for k, v in bals.items())
        log.info("%s starting balances %s", venue, bal_str)
    else:
        log.info("%s starting balances none", venue)


def _balances_brief(adapter: ExchangeAdapter, max_items: int = 4) -> str:
    """Return a compact string of non-zero balances for Discord/log lines.

    Example: "bal USDT=120.0, BTC=0.01" or "bal none".
    """

    try:
        bals = adapter.balances() or {}
    except Exception:
        return "bal n/a"
    if not bals:
        return "bal none"
    # Prefer common assets first, then by value desc
    priority = {"USDT": 100, "USDC": 90, "BTC": 80, "ETH": 70}
    items = sorted(
        bals.items(), key=lambda kv: (-(priority.get(kv[0], 0)), -float(kv[1]))
    )[:max_items]
    return "bal " + ", ".join(f"{k}={float(v):.6g}" for k, v in items)


async def _live_run_for_venue(
    venue: str,
    *,
    symbols: str | None = None,
    auto_suggest_top: int = 0,
    attempt_notify_override: bool | None = None,
):
    """Run the continuous live loop for a single venue (async)."""

    a = _build_adapter(venue, settings)
    _log_balances(venue, a)
    conn = init_db(settings.sqlite_path)
    tris = _triangles_for(venue)
    # Optional: filter triangles by CSV of symbols (must include all three legs)
    if symbols:
        allowed = {s.strip() for s in symbols.split(",") if s.strip()}
        if allowed:
            tris = [
                t
                for t in tris
                if all(leg in allowed for leg in (t.leg_ab, t.leg_bc, t.leg_ac))
            ]
    # Filter out triangles with legs not listed by the venue (defensive)
    try:
        ms = a.load_markets()
        missing: list[tuple[Triangle, list[str]]] = []
        kept: list[Triangle] = []
        is_alpaca = a.name().lower() == "alpaca"
        map_usdt = bool(getattr(settings, "alpaca_map_usdt_to_usd", False))

        def _supported(leg: str) -> bool:
            if leg in ms:
                return True
            if (
                is_alpaca
                and map_usdt
                and isinstance(leg, str)
                and leg.upper().endswith("/USDT")
            ):
                alt = leg[:-5] + "/USD"
                return alt in ms
            return False

        for t in tris:
            legs = [t.leg_ab, t.leg_bc, t.leg_ac]
            miss = [leg for leg in legs if not _supported(leg)]
            if miss:
                missing.append((t, miss))
            else:
                kept.append(t)
        tris = kept
    except Exception:
        pass
    if not tris:
        # Try suggest triangles programmatically
        suggestions: list[list[str]] = []
        try:
            ms = a.load_markets()
            suggestions = _discover_triangles_from_markets(ms)[:3]
        except Exception:
            suggestions = []
        # If requested, auto-use top-N suggestions for this session only
        use_count = int(auto_suggest_top or 0)
        if use_count > 0 and suggestions:
            chosen = suggestions[:use_count]
            tris = [Triangle(*t) for t in chosen]
            try:
                notify_discord(
                    venue,
                    (
                        f"[live@{venue}] using auto-suggested triangles for session: "
                        f"{'; '.join('|'.join(t) for t in chosen)} | {_balances_brief(a)}"
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
                        f"{x.leg_ab}|{x.leg_bc}|{x.leg_ac} -> missing {','.join(m)}"
                        for x, m in (missing if "missing" in locals() else [])
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
                        f"suggestions={('; '.join('|'.join(t) for t in suggestions)) if suggestions else 'n/a'} | {_balances_brief(a)}"
                    ),
                )
            except Exception:
                pass
            return
    # Status banner: show active triangles after filtering and market check
    if tris:
        tri_list = ", ".join(f"{t.leg_ab}|{t.leg_bc}|{t.leg_ac}" for t in tris)
        log.info(
            "live@%s active triangles=%d -> %s",
            venue,
            len(tris),
            tri_list,
        )
        # Send a one-time Discord notice of active triangles for visibility
        try:
            notify_discord(
                venue,
                f"[live@{venue}] active triangles={len(tris)} -> {tri_list} | {_balances_brief(a)}",
            )
        except Exception:
            pass
    for tri in tris:
        insert_triangle(conn, tri)
    log.info("live@%s dry_run=%s", venue, settings.dry_run)
    # Discord notify controls
    last_hb_at = time.time()
    last_trade_notify_at = 0.0
    last_attempt_notify_at = 0.0
    # Global min notify interval for all Discord notifications
    min_interval = float(
        getattr(settings, "discord_min_notify_interval_secs", 10.0) or 10.0
    )
    attempt_notify = (
        bool(attempt_notify_override)
        if attempt_notify_override is not None
        else bool(getattr(settings, "discord_attempt_notify", False))
    )
    # Streaming execution loop
    start_time = time.time()
    attempts_total = 0
    successes_total = 0
    net_total = 0.0
    latency_total = 0.0
    skip_counts: dict[str, int] = {}
    try:
        async for tri, res, reasons, latency in stream_triangles(
            a, tris, float(getattr(settings, "net_threshold_bps", 0) or 0) / 10000.0
        ):
            CYCLE_LATENCY.labels(venue).observe(latency)
            attempts_total += 1
            latency_total += float(latency or 0.0)
            if res is None:
                # Collect skip reasons for periodic summary/diagnosis
                for r in reasons or ["unknown"]:
                    skip_counts[r] = skip_counts.get(r, 0) + 1
                # Optional per-attempt skip notification (rate-limited)
                if attempt_notify and (time.time() - last_attempt_notify_at) > min_interval:
                    try:
                        rs = ",".join(reasons or ["unknown"])[:200]
                        notify_discord(
                            venue,
                            f"[live@{venue}] attempt SKIP {tri} reasons={rs}",
                        )
                    except Exception:
                        pass
                    last_attempt_notify_at = time.time()
                continue
            # Record attempt
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
            # Persist fills and log
            try:
                PROFIT_TOTAL.labels(venue).set(res["realized_usdt"])
                ORDERS_TOTAL.labels(venue, "ok").inc()
            except Exception:
                pass
            for f in res.get("fills") or []:
                try:
                    insert_fill(
                        conn,
                        Fill(
                            order_id=str(f.get("id", "")),
                            symbol=str(f.get("symbol", "")),
                            side=str(f.get("side", "")),
                            price=float(f.get("price", 0.0)),
                            quantity=float(f.get("qty", 0.0)),
                            fee=float(f.get("fee", 0.0)),
                            timestamp=None,
                            venue=venue,
                            leg=str(f.get("leg") or ""),
                            tif=str(f.get("tif") or ""),
                            order_type=str(f.get("type") or ""),
                            fee_rate=(
                                float(f.get("fee_rate"))
                                if f.get("fee_rate") is not None
                                else None
                            ),
                            notional=float(f.get("price", 0.0))
                            * float(f.get("qty", 0.0)),
                            dry_run=bool(getattr(settings, "dry_run", True)),
                            attempt_id=attempt_id,
                        ),
                    )
                    FILLS_TOTAL.labels(venue).inc()
                except Exception as e:
                    log.error("persist fill error: %s", e)
            log.info(
                "%s %s net=%.3f%% (est. profit after fees) PnL=%.2f USDT",
                venue,
                tri,
                res["net_est"] * 100,
                res["realized_usdt"],
            )
            # Per-attempt success notification or legacy trade notify (rate-limited)
            if (time.time() - last_trade_notify_at) > min_interval:
                try:
                    qty = (
                        float(res["fills"][0]["qty"]) if res and res.get("fills") else None
                    )
                    if attempt_notify:
                        msg = (
                            f"[live@{venue}] attempt OK {tri} net={res['net_est']*100:.2f}% "
                            f"pnl={res['realized_usdt']:.4f} USDT "
                        )
                        if attempt_id is not None:
                            msg += f"attempt_id={attempt_id} "
                        if qty is not None:
                            msg += f"qty={qty:.6g} "
                        msg += f"slip_bps={getattr(settings, 'max_slippage_bps', 0)} | {_balances_brief(a)}"
                        notify_discord(venue, msg)
                        last_trade_notify_at = time.time()
                    elif bool(getattr(settings, "discord_trade_notify", False)):
                        msg = (
                            f"[{venue}] TRADE {tri} net={res['net_est'] * 100:.2f}% "
                            f"pnl={res['realized_usdt']:.4f} USDT "
                        )
                        if attempt_id is not None:
                            msg += f"attempt_id={attempt_id} "
                        if qty is not None:
                            msg += f"qty={qty:.6g} "
                        msg += f"slip_bps={getattr(settings, 'max_slippage_bps', 0)} | {_balances_brief(a)}"
                        notify_discord(venue, msg)
                        last_trade_notify_at = time.time()
                except Exception:
                    pass

            # Periodic Discord heartbeat summary
            hb_interval = float(
                getattr(settings, "discord_heartbeat_secs", 60.0) or 60.0
            )
            if hb_interval > 0 and time.time() - last_hb_at > hb_interval:
                # Console heartbeat for local visibility
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
                        # Show top 3 skip reasons by count for quick diagnosis
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
    finally:
        try:
            await a.close()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass


@app.command("yield:collect")
@app.command("yield_collect")
def yield_collect(
    asset: str = "USDC",
    min_stake: int | None = None,
    reserve_usd: float | None = None,
    help_verbose: bool = False,
):
    """Deposit idle stablecoin into Aave v3 (beta, USDC only).

    Uses on-chain wallet balance (RPC_URL/PRIVATE_KEY) and keeps a configured
    USD reserve in the wallet. In dry-run mode, logs intended actions only.
    """

    if help_verbose:
        typer.echo(
            "Deposits idle wallet USDC to Aave v3. Requires RPC_URL and PRIVATE_KEY.\n"
            "Reserves are computed as max(reserve_amount_usd, reserve_percent * balance_usd).\n"
            "Amounts are in token units: USDC uses 6 decimals. Honors global DRY_RUN."
        )
        raise SystemExit(0)

    asset = (asset or "").strip().upper()
    if asset != "USDC":
        log.error("yield:collect supports USDC only for now")
        return

    # Start metrics server if not already running
    try:
        start_metrics_server(settings.prom_port)
        # short-circuit legacy inline implementation; use async helper below
        raise RuntimeError("switch to _live_run_for_venue")
    except Exception:
        pass

    provider = AaveProvider(settings)
    # Open DB for persistence (best-effort)
    try:
        conn = init_db(settings.sqlite_path)
    except Exception:
        conn = None
    bal_raw = int(provider.get_wallet_balance_raw())
    atoken_before = int(provider.get_deposit_balance_raw())
    # 6 decimals for USDC
    bal_usd = bal_raw / 1_000_000.0

    # Determine reserve
    reserve_abs = (
        float(reserve_usd)
        if reserve_usd is not None
        else float(getattr(settings, "reserve_amount_usd", 0.0))
    )
    _rp = getattr(settings, "reserve_percent", 0.0)
    try:
        reserve_pct = float(_rp) / 100.0
    except Exception:
        reserve_pct = 0.0
    reserve_pct_amt = bal_usd * reserve_pct if reserve_pct > 0 else 0.0
    reserve_final = max(reserve_abs, reserve_pct_amt)

    available_usd = max(bal_usd - reserve_final, 0.0)
    amount_raw = int(available_usd * 1_000_000)
    # Default minimum stake from settings
    min_units = (
        int(min_stake)
        if min_stake is not None
        else int(getattr(settings, "min_usdc_stake", 1_000_000))
    )

    if amount_raw < min_units:
        log.info(
            "nothing to do: balance=%.2f USDC reserve=%.2f min_stake=%.2f",
            bal_usd,
            reserve_final,
            min_units / 1_000_000.0,
        )
        return

    if bool(getattr(settings, "dry_run", True)):
        log.info(
            "[dry-run] would deposit %.2f USDC to Aave (reserve=%.2f)",
            amount_raw / 1_000_000.0,
            reserve_final,
        )
        try:
            YIELD_DEPOSITS_TOTAL.labels("aave", "dry_run").inc()
        except Exception:
            pass
        # Persist dry-run intention
        try:
            if conn is not None:
                insert_yield_op(
                    conn,
                    ts_iso=datetime.now(timezone.utc).isoformat(),
                    provider="aave",
                    op="deposit",
                    asset=asset,
                    amount_raw=amount_raw,
                    mode="dry_run",
                    error=None,
                    wallet_raw_before=bal_raw,
                    atoken_raw_before=atoken_before,
                    wallet_raw_after=bal_raw,
                    atoken_raw_after=atoken_before,
                    tx_hash=None,
                )
        except Exception:
            pass
        try:
            notify_discord(
                "yield",
                (
                    "[yield] DRY-RUN deposit "
                    f"{fmt_usd(amount_raw / 1_000_000.0)} USDC to Aave | reserve {fmt_usd(reserve_final)} USDC"
                ),
            )
        except Exception:
            pass
        return

    try:
        provider.deposit_raw(amount_raw)
        log.info(
            "deposited %.2f USDC to Aave (kept reserve=%.2f)",
            amount_raw / 1_000_000.0,
            reserve_final,
        )
        try:
            YIELD_DEPOSITS_TOTAL.labels("aave", "live").inc()
        except Exception:
            pass
        # Persist live op (tx hash not returned by stake.py)
        try:
            if conn is not None:
                insert_yield_op(
                    conn,
                    ts_iso=datetime.now(timezone.utc).isoformat(),
                    provider="aave",
                    op="deposit",
                    asset=asset,
                    amount_raw=amount_raw,
                    mode="live",
                    error=None,
                    wallet_raw_before=bal_raw,
                    atoken_raw_before=atoken_before,
                    wallet_raw_after=int(provider.get_wallet_balance_raw()),
                    atoken_raw_after=int(provider.get_deposit_balance_raw()),
                    tx_hash=None,
                )
        except Exception:
            pass
        try:
            notify_discord(
                "yield",
                (
                    "[yield] deposited "
                    f"{fmt_usd(amount_raw / 1_000_000.0)} USDC to Aave | reserve {fmt_usd(reserve_final)} USDC"
                ),
            )
        except Exception:
            pass
    except Exception as e:  # pragma: no cover - depends on chain state
        log.error("yield:collect deposit error: %s", e)
        try:
            YIELD_ERRORS_TOTAL.labels("deposit").inc()
        except Exception:
            pass
        # Persist error
        try:
            if conn is not None:
                insert_yield_op(
                    conn,
                    ts_iso=datetime.now(timezone.utc).isoformat(),
                    provider="aave",
                    op="deposit",
                    asset=asset,
                    amount_raw=amount_raw,
                    mode="live",
                    error=str(e),
                    wallet_raw_before=bal_raw,
                    atoken_raw_before=atoken_before,
                    wallet_raw_after=None,
                    atoken_raw_after=None,
                    tx_hash=None,
                )
        except Exception:
            pass


@app.command("yield:withdraw")
@app.command("yield_withdraw")
def yield_withdraw(
    asset: str = "USDC",
    amount_usd: float | None = None,
    all_excess: bool = False,
    reserve_usd: float | None = None,
    help_verbose: bool = False,
):
    """Withdraw USDC from Aave v3 Pool back into the wallet.

    Specify an explicit amount via --amount-usd or use --all-excess to withdraw
    everything above the configured reserve. Honors global DRY_RUN.
    """

    if help_verbose:
        typer.echo(
            "Withdraws USDC from Aave v3. Use --amount-usd for a fixed amount or --all-excess to leave only the reserve."
        )
        raise SystemExit(0)

    asset = (asset or "").strip().upper()
    if asset != "USDC":
        log.error("yield:withdraw supports USDC only for now")
        return

    # Start metrics server if not already running
    try:
        start_metrics_server(settings.prom_port)
    except Exception:
        pass

    provider = AaveProvider(settings)

    # If all_excess, compute based on wallet balance (assumes aToken redemption immediate)
    reserve_abs = (
        float(reserve_usd)
        if reserve_usd is not None
        else float(getattr(settings, "reserve_amount_usd", 0.0))
    )
    _rp = getattr(settings, "reserve_percent", 0.0)
    try:
        reserve_pct = float(_rp) / 100.0
    except Exception:
        reserve_pct = 0.0

    # Open DB for persistence (best-effort)
    try:
        conn = init_db(settings.sqlite_path)
    except Exception:
        conn = None
    bal_raw = int(provider.get_wallet_balance_raw())
    bal_usd = bal_raw / 1_000_000.0
    reserve_pct_amt = bal_usd * reserve_pct if reserve_pct > 0 else 0.0
    reserve_final = max(reserve_abs, reserve_pct_amt)

    if amount_usd is None and not all_excess:
        log.error("Specify --amount-usd or --all-excess")
        return

    if all_excess:
        # Withdraw down to reserve. Prefer aToken balance if configured; else top-up if below reserve.
        atoken_raw = provider.get_deposit_balance_raw()
        atoken_usd = atoken_raw / 1_000_000.0
        if bal_usd >= reserve_final:
            log.info(
                "nothing to do: wallet >= reserve (%.2f >= %.2f)",
                bal_usd,
                reserve_final,
            )
            return
        # Target top-up = reserve - wallet; cap by aToken balance when available
        target = reserve_final - bal_usd
        if atoken_raw > 0:
            amount_usd = min(target, atoken_usd)
        else:
            amount_usd = target

    amount_raw = int(max(float(amount_usd or 0.0), 0.0) * 1_000_000)
    if amount_raw <= 0:
        log.error("withdraw amount must be positive")
        return

    if bool(getattr(settings, "dry_run", True)):
        log.info(
            "[dry-run] would withdraw %.2f USDC from Aave", amount_raw / 1_000_000.0
        )
        try:
            YIELD_WITHDRAWS_TOTAL.labels("aave", "dry_run").inc()
        except Exception:
            pass
        # Persist dry-run intention
        try:
            if conn is not None:
                insert_yield_op(
                    conn,
                    ts_iso=datetime.now(timezone.utc).isoformat(),
                    provider="aave",
                    op="withdraw",
                    asset=asset,
                    amount_raw=amount_raw,
                    mode="dry_run",
                    error=None,
                    wallet_raw_before=bal_raw,
                    atoken_raw_before=int(provider.get_deposit_balance_raw()),
                    wallet_raw_after=bal_raw,
                    atoken_raw_after=int(provider.get_deposit_balance_raw()),
                    tx_hash=None,
                )
        except Exception:
            pass
        try:
            notify_discord(
                "yield",
                (
                    "[yield] DRY-RUN withdraw "
                    f"{fmt_usd(amount_raw / 1_000_000.0)} USDC from Aave"
                ),
            )
        except Exception:
            pass
        return

    try:
        provider.withdraw_raw(amount_raw)
        log.info("withdrew %.2f USDC from Aave", amount_raw / 1_000_000.0)
        try:
            YIELD_WITHDRAWS_TOTAL.labels("aave", "live").inc()
        except Exception:
            pass
        # Persist live op
        try:
            if conn is not None:
                insert_yield_op(
                    conn,
                    ts_iso=datetime.now(timezone.utc).isoformat(),
                    provider="aave",
                    op="withdraw",
                    asset=asset,
                    amount_raw=amount_raw,
                    mode="live",
                    error=None,
                    wallet_raw_before=bal_raw,
                    atoken_raw_before=int(provider.get_deposit_balance_raw()),
                    wallet_raw_after=int(provider.get_wallet_balance_raw()),
                    atoken_raw_after=int(provider.get_deposit_balance_raw()),
                    tx_hash=None,
                )
        except Exception:
            pass
        try:
            notify_discord(
                "yield",
                (
                    "[yield] withdrew "
                    f"{fmt_usd(amount_raw / 1_000_000.0)} USDC from Aave"
                ),
            )
        except Exception:
            pass
    except Exception as e:  # pragma: no cover
        log.error("yield:withdraw error: %s", e)
        try:
            YIELD_ERRORS_TOTAL.labels("withdraw").inc()
        except Exception:
            pass
        # Persist error
        try:
            if conn is not None:
                insert_yield_op(
                    conn,
                    ts_iso=datetime.now(timezone.utc).isoformat(),
                    provider="aave",
                    op="withdraw",
                    asset=asset,
                    amount_raw=amount_raw,
                    mode="live",
                    error=str(e),
                    wallet_raw_before=bal_raw,
                    atoken_raw_before=int(provider.get_deposit_balance_raw()),
                    wallet_raw_after=None,
                    atoken_raw_after=None,
                    tx_hash=None,
                )
        except Exception:
            pass


@app.command("yield:watch")
@app.command("yield_watch")
def yield_watch(
    asset: str = "USDC",
    sources: str | None = None,
    interval: float = 60.0,
    apr_hint: float | None = None,
    min_delta_bps: int = 50,
):
    """Periodically fetch APRs and alert if a better yield is found.

    Sources may be a CSV of URLs or a JSON array of URLs. Each URL should
    return a JSON object or list with items like:
    {"provider": "aave", "asset": "USDC", "apr_percent": 3.25}.
    """

    import json as _json
    import os as _os
    import urllib.request as _rq

    def _parse_sources(s: str | None) -> list[str]:
        if not s:
            return []
        s = s.strip()
        try:
            arr = _json.loads(s)
            if isinstance(arr, list):
                return [str(u) for u in arr]
        except Exception:
            pass
        return [u.strip() for u in s.split(",") if u.strip()]

    urls = _parse_sources(sources)
    asset_u = (asset or "").strip().upper() or "USDC"
    target_apr = float(apr_hint) if apr_hint is not None else None
    min_delta = float(min_delta_bps) / 100.0

    log.info(
        "yield:watch asset=%s interval=%.1fs sources=%d min_delta=%.2f%%",
        asset_u,
        interval,
        len(urls),
        min_delta,
    )

    # Expose Prometheus metrics if a collector is scraping
    try:
        start_metrics_server(settings.prom_port)
    except Exception:
        pass

    while True:
        try:
            YIELD_CHECKS_TOTAL.inc()
        except Exception:
            pass

        best_apr = 0.0
        best_provider = None
        for url in urls:
            try:
                # Support local files (absolute/relative) and file:// scheme
                data: bytes
                if url.startswith("file://"):
                    path = url[len("file://") :]
                    with open(path, "rb") as fh:
                        data = fh.read()
                elif _os.path.exists(url):
                    with open(url, "rb") as fh:
                        data = fh.read()
                else:
                    with _rq.urlopen(url, timeout=5) as resp:
                        data = resp.read()
                doc = _json.loads(data)
            except Exception:
                continue
            items = doc if isinstance(doc, list) else [doc]
            for it in items:
                try:
                    if (str(it.get("asset", asset_u))).upper() != asset_u:
                        continue
                    provider = str(it.get("provider") or "unknown")
                    apr = float(it.get("apr_percent") or 0.0)
                except Exception:
                    continue
                try:
                    YIELD_APR.labels(provider, asset_u).set(apr)
                except Exception:
                    pass
                if apr > best_apr:
                    best_apr, best_provider = apr, provider

        try:
            YIELD_BEST_APR.labels(asset_u).set(best_apr)
        except Exception:
            pass

        if target_apr is not None and best_apr >= target_apr + min_delta:
            msg = (
                f"Better {asset_u} yield: {best_provider} {best_apr:.2f}% "
                f"(current {target_apr:.2f}% +{min_delta:.2f}% threshold)"
            )
            log.info(msg)
            try:
                YIELD_ALERTS_TOTAL.labels(asset_u).inc()
            except Exception:
                pass
            notify_discord("yield", msg)

        time.sleep(max(interval, 1.0))


@app.command("keys:check")
@app.command("keys_check")
def keys_check():
    """Validate exchange credentials by fetching a sample order book."""
    for venue in settings.exchanges:
        try:
            a = _build_adapter(venue, settings)
            ms = a.load_markets()
            symbol = (
                "BTC/USDT"
                if "BTC/USDT" in ms
                else "BTC/USD" if "BTC/USD" in ms else next(iter(ms))
            )
            ob = a.fetch_orderbook(symbol, 1)
            bid = ob.get("bids", [])
            ask = ob.get("asks", [])
            bid_price = bid[0][0] if bid else "n/a"
            ask_price = ask[0][0] if ask else "n/a"
            log.info(
                "[%s] markets=%d %s %s/%s",
                a.name(),
                len(ms),
                symbol,
                bid_price,
                ask_price,
            )
        except Exception as e:
            log.error("[%s] ERROR: %s", venue, e)


@app.command("markets:limits")
@app.command("markets_limits")
def markets_limits(
    venue: str = "alpaca",
    symbols: str | None = None,
):
    """List min-notional (cost.min) and maker/taker fees for symbols.

    Use ``--symbols`` to filter by a comma-separated list, otherwise prints
    entries for the configured triangles for quick relevance.
    """

    a = _build_adapter(venue, settings)
    try:
        ms = a.load_markets()
    except Exception:
        ms = {}

    selected: list[str]
    if symbols:
        selected = [s.strip() for s in symbols.split(",") if s.strip()]
    else:
        tris = _triangles_for(venue)
        selected = sorted({s for t in tris for s in (t.leg_ab, t.leg_bc, t.leg_ac)})

    for s in selected:
        if ms and s not in ms:
            log.info("%s not in markets; skipping", s)
            continue
        try:
            maker, taker = a.fetch_fees(s)
        except Exception:
            maker, taker = 0.0, 0.0
        try:
            min_cost = float(a.min_notional(s))
        except Exception:
            min_cost = 0.0
        log.info(
            "%s min_cost=%.6g maker=%d bps taker=%d bps",
            s,
            min_cost,
            int(round(maker * 1e4)),
            int(round(taker * 1e4)),
        )


@app.command("config:recommend")
@app.command("config_recommend")
def config_recommend(
    venue: str = "alpaca",
):
    """Suggest starter Strategy settings based on current venue data.

    Heuristics:
    - Threshold = (avg taker across legs * 3 + 5 bps) rounded up
    - Notional = max(2 × min_notional(AB), $5)
    - Slippage = 8 bps default
    """

    a = _build_adapter(venue, settings)
    _log_balances(venue, a)
    tris = _triangles_for(venue)
    tri = tris[0]
    legs = [tri.leg_ab, tri.leg_bc, tri.leg_ac]
    takers: list[float] = []
    for s in legs:
        try:
            takers.append(a.fetch_fees(s)[1])
        except Exception:
            takers.append(0.001)
    avg_taker = sum(takers) / max(len(takers), 1)
    thresh_bps = int((avg_taker * 3 * 1e4) + 5)  # +5 bps buffer

    try:
        min_cost_ab = float(a.min_notional(tri.leg_ab))
    except Exception:
        min_cost_ab = 1.0
    # Ensure a practical floor for notional suggestion
    notional_usd = max(2.0 * min_cost_ab, 5.0)

    # Recommend defaults
    rec = {
        "NOTIONAL_PER_TRADE_USD": int(round(notional_usd)),
        "NET_THRESHOLD_BPS": max(thresh_bps, 10),
        "MAX_SLIPPAGE_BPS": 8,
        "DRY_RUN": True,
    }
    # Print a compact single-line summary for easy copy/paste
    log.info(
        "Recommend: NOTIONAL_PER_TRADE_USD=%s NET_THRESHOLD_BPS=%s MAX_SLIPPAGE_BPS=%s DRY_RUN=%s",
        rec["NOTIONAL_PER_TRADE_USD"],
        rec["NET_THRESHOLD_BPS"],
        rec["MAX_SLIPPAGE_BPS"],
        str(rec["DRY_RUN"]).lower(),
    )
    # And a bit more context
    log.info(
        "Reference: avg_taker=%d bps legs=%s min_notional_ab=%.6g",
        int(round(avg_taker * 1e4)),
        ",".join(legs),
        min_cost_ab,
    )


@app.command("hybrid")
def fitness_hybrid(
    legs: str = "ETH/USDT,ETH/BTC,BTC/USDT",
    venues: str | None = None,
    secs: int = 10,
):
    """Read-only multi-venue net% estimate using per-leg venue mapping.

    Example:
      --legs "SOL/USDT,SOL/BTC,BTC/USDT" \
      --venues "SOL/USDT=kraken,SOL/BTC=kraken,BTC/USDT=alpaca"

    Notes:
    - Estimates only; does not place orders or run dry-run simulation.
    - Uses taker fee per leg when available and compounds fees across legs.
    """

    def _parse_csv(s: str | None) -> list[str]:
        if not s:
            return []
        return [i.strip() for i in s.split(",") if i.strip()]

    def _parse_map(s: str | None) -> dict[str, str]:
        out: dict[str, str] = {}
        for item in _parse_csv(s):
            if "=" in item:
                sym, ven = item.split("=", 1)
                sym = sym.strip()
                ven = ven.strip()
                if sym and ven:
                    out[sym] = ven
        return out

    legs_list = _parse_csv(legs)
    if len(legs_list) != 3:
        log.error("--legs must provide exactly three symbols (AB,BC,AC)")
        raise SystemExit(2)
    leg_ab, leg_bc, leg_ac = legs_list
    vmap = _parse_map(venues)
    used_venues = {vmap.get(leg_ab, ""), vmap.get(leg_bc, ""), vmap.get(leg_ac, "")}
    used_venues = {v for v in used_venues if v}

    # Build adapters for venues referenced; default to 'kraken' if none provided
    adapters: dict[str, CCXTAdapter] = {}
    for ven in used_venues or {"kraken"}:
        adapters[ven] = _build_adapter(ven, settings)

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

    def _taker(ven: str, sym: str) -> float:
        try:
            return adapters[ven].fetch_fees(sym)[1]
        except Exception:
            return 0.001

    import time as _time

    t0 = _time.time()
    while _time.time() - t0 < secs:
        # Fetch books per leg from mapped venues (default to the only adapter if single-venue)
        ven_ab = vmap.get(leg_ab) or next(iter(adapters))
        ven_bc = vmap.get(leg_bc) or next(iter(adapters))
        ven_ac = vmap.get(leg_ac) or next(iter(adapters))
        try:
            ob_ab = adapters[ven_ab].fetch_orderbook(leg_ab, 1)
            ob_bc = adapters[ven_bc].fetch_orderbook(leg_bc, 1)
            ob_ac = adapters[ven_ac].fetch_orderbook(leg_ac, 1)
        except Exception as e:
            log.warning("fitness:hybrid fetch error: %s", e)
            _time.sleep(1.0)
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
            _time.sleep(1.0)
            continue
        # Compute gross and per-leg taker compounding
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
        _time.sleep(1.0)
    # end of hybrid


@app.command("notify:test")
@app.command("notify_test")
def notify_test(message: str = "[notify] test message from arbit.cli"):
    """Send a test message to the configured Discord webhook."""

    if not getattr(settings, "discord_webhook_url", None):
        log.error("notify:test no webhook configured (set DISCORD_WEBHOOK_URL)")
        return
    try:
        notify_discord("notify", message)
    except Exception as e:  # defensive; notify_discord already swallows errors
        log.error("notify:test error: %s", e)


@app.command("config:discover")
@app.command("config_discover")
def config_discover(
    venue: str = "kraken",
    write_env: bool = False,
    env_path: str = ".env",
):
    """Discover supported triangles for a venue and optionally write to .env."""

    a = _build_adapter(venue, settings)
    try:
        ms = a.load_markets()
    except Exception as e:
        log.error("load_markets failed for %s: %s", venue, e)
        raise SystemExit(1)
    triples = _discover_triangles_from_markets(ms)
    typer.echo(
        f"{venue} triangles={len(triples)} "
        + (f"first={'|'.join(triples[0])}" if triples else "")
    )
    if write_env:
        ok = _update_env_triangles(venue, triples, env_path)  # noqa: F821
        if ok:
            typer.echo(f"wrote TRIANGLES_BY_VENUE for {venue} to {env_path}")
        else:
            typer.echo(f"failed to write {env_path}")


@app.command()
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
):
    """Read-only sanity check that prints bid/ask spreads.

    When ``--simulate`` is provided, attempt dry-run triangle executions using
    current order books and log simulated PnL. Use ``--persist`` to store
    simulated fills in SQLite for later analysis. Current account balances are
    logged at startup for supported venues.
    """

    if help_verbose:
        typer.echo(
            "Typical log line: 'kraken ETH/USDT spread=0.5 bps' where spread is the\n"
            "bid/ask gap expressed in basis points (1/100th of a percent)."
        )
        typer.echo(
            "Use --simulate to attempt dry-run triangle executions and log net%/PnL."
        )
        typer.echo(
            "Use --dummy-trigger to inject one synthetic profitable triangle in fitness"
            " mode to exercise the execution path without placing real orders."
        )
        typer.echo(
            "Use --symbols 'A/B,C/D,...' to restrict triangles by legs (all legs must match)."
        )
        typer.echo(
            "Use --discord-heartbeat-secs to send periodic summaries to Discord (0=off)."
        )
        raise SystemExit(0)

    a = _build_adapter(venue, settings)
    _log_balances(venue, a)
    tris = _triangles_for(venue)
    # Optional: filter triangles by CSV of symbols (must include all three legs)
    allowed: set[str] | None = None
    if symbols:
        allowed = {s.strip() for s in symbols.split(",") if s.strip()}
        if allowed:
            tris = [
                t
                for t in tris
                if all(leg in allowed for leg in (t.leg_ab, t.leg_bc, t.leg_ac))
            ]
    t0 = time.time()
    syms = {s for t in tris for s in (t.leg_ab, t.leg_bc, t.leg_ac)}
    # Status banner: show active triangles and legs after filters
    if tris:
        tri_list = ", ".join(f"{t.leg_ab}|{t.leg_bc}|{t.leg_ac}" for t in tris)
        log.info(
            "fitness@%s active triangles=%d symbols=%d -> %s",
            venue,
            len(tris),
            len(syms),
            tri_list,
        )

    # Optional persistence for simulated fills
    conn = None
    if simulate and persist:
        conn = init_db(settings.sqlite_path)
        for tri in tris:
            try:
                insert_triangle(conn, tri)
            except Exception:
                pass

    # Force dry-run behavior during simulation regardless of global setting
    prev_dry_run = settings.dry_run
    if simulate:
        try:
            settings.dry_run = True
        except Exception:
            pass

    sim_count = 0
    sim_pnl = 0.0
    attempts_total = 0
    from collections import defaultdict

    skip_counts: dict[str, int] = defaultdict(int)
    loop_idx = 0
    last_hb_at = 0.0
    # Resolve per-attempt notify preference and rate limit
    attempt_notify = (
        bool(attempt_notify)
        if attempt_notify is not None
        else bool(getattr(settings, "discord_attempt_notify", False))
    )
    last_attempt_notify_at = 0.0
    min_interval = float(
        getattr(settings, "discord_min_notify_interval_secs", 10.0) or 10.0
    )
    try:
        while time.time() - t0 < secs:
            books_cache: dict[str, dict] = {}
            # Spread sampling per symbol
            for s in syms:
                try:
                    ob = a.fetch_orderbook(s, 5)
                except Exception as e:
                    log.warning("%s fetch_orderbook skip %s: %s", venue, s, e)
                    continue
                books_cache[s] = ob
                if ob.get("bids") and ob.get("asks"):
                    spread = (
                        (ob["asks"][0][0] - ob["bids"][0][0]) / ob["asks"][0][0]
                    ) * 1e4  # bid/ask gap in basis points
                    log.info("%s %s spread=%.1f bps (ask-bid gap)", venue, s, spread)

            # Optional: try triangles in dry-run and log/persist
            if simulate:
                # Optionally inject a synthetic profitable setup once to
                # validate the execution path in fitness mode.
                injected: dict[str, dict] | None = None
                if dummy_trigger and loop_idx == 0 and tris:
                    tri0 = tris[0]
                    # Craft generous top-of-book values that yield a clear edge
                    # with sufficient size to pass min-notional checks.
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

                for tri in tris:
                    skip_reasons: list[str] = []
                    try:
                        t_start = time.time()
                        # If we injected synthetic books for this triangle,
                        # temporarily serve them for top-of-book lookups used
                        # by slippage guards and dry-run fills.
                        if injected and tri.leg_ab in injected:
                            orig_fetch = a.fetch_orderbook

                            def _patched_fetch(sym: str, depth: int = 1):
                                if (
                                    depth == 1 and sym in injected
                                ):  # serve injected top-of-book
                                    # Reduce to 1 level to match depth request
                                    ob = injected[sym]
                                    return {
                                        "bids": [ob["bids"][0]],
                                        "asks": [ob["asks"][0]],
                                    }
                                return orig_fetch(sym, depth)

                            a.fetch_orderbook = _patched_fetch  # type: ignore[assignment]

                        attempts_total += 1
                        res = try_triangle(
                            a,
                            tri,
                            books_cache,
                            settings.net_threshold_bps / 10000.0,
                            skip_reasons,
                        )
                    except Exception as e:  # defensive: keep fitness resilient
                        log.error("simulate error for %s: %s", tri, e)
                        continue
                    finally:
                        if injected and tri.leg_ab in injected:
                            a.fetch_orderbook = orig_fetch  # type: ignore[assignment]
                    # Persist an attempt record with top-of-book snapshot
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
                        ok = bool(res)
                        net_est = float(res.get("net_est", 0.0)) if res else None
                        realized = float(res.get("realized_usdt", 0.0)) if res else None
                        qty_base = None
                        if res and res.get("fills"):
                            try:
                                qty_base = float(
                                    res["fills"][0]["qty"]
                                )  # AB leg quantity
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
                    if not res:
                        # Count skips by reason (no metrics emission in fitness)
                        if skip_reasons:
                            for r in skip_reasons:
                                skip_counts[r] = skip_counts.get(r, 0) + 1
                        else:
                            skip_counts["unprofitable"] = (
                                skip_counts.get("unprofitable", 0) + 1
                            )
                        # Optional per-attempt SKIP notification
                        if attempt_notify and (time.time() - last_attempt_notify_at) > min_interval:
                            try:
                                rs = ",".join(skip_reasons or ["unknown"])[:200]
                                notify_discord(
                                    venue,
                                    f"[fitness@{venue}] attempt SKIP {tri} reasons={rs}",
                                )
                            except Exception:
                                pass
                            last_attempt_notify_at = time.time()
                        continue
                    sim_count += 1
                    sim_pnl += float(res.get("realized_usdt", 0.0))
                    # Optional per-attempt OK notification (simulate)
                    if attempt_notify and (time.time() - last_attempt_notify_at) > min_interval:
                        try:
                            qty = (
                                float(res["fills"][0]["qty"]) if res and res.get("fills") else None
                            )
                            msg = (
                                f"[fitness@{venue}] attempt OK {tri} net={res['net_est']*100:.2f}% "
                                f"pnl={res['realized_usdt']:.4f} USDT "
                            )
                            if qty is not None:
                                msg += f"qty={qty:.6g} "
                            msg += f"slip_bps={getattr(settings, 'max_slippage_bps', 0)}"
                            notify_discord(venue, msg)
                        except Exception:
                            pass
                        last_attempt_notify_at = time.time()
                    for f in res.get("fills", []):
                        if conn is not None:
                            try:
                                insert_fill(
                                    conn,
                                    Fill(
                                        order_id=str(f.get("id", "")),
                                        symbol=str(f.get("symbol", "")),
                                        side=str(f.get("side", "")),
                                        price=float(f.get("price", 0.0)),
                                        quantity=float(f.get("qty", 0.0)),
                                        fee=float(f.get("fee", 0.0)),
                                        timestamp=None,
                                        venue=venue,
                                        leg=str(f.get("leg") or ""),
                                        tif=str(f.get("tif") or ""),
                                        order_type=str(f.get("type") or ""),
                                        fee_rate=(
                                            float(f.get("fee_rate"))
                                            if f.get("fee_rate") is not None
                                            else None
                                        ),
                                        notional=float(f.get("price", 0.0))
                                        * float(f.get("qty", 0.0)),
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
                        "%s [sim] %s net=%.3f%% PnL=%.2f USDT",
                        venue,
                        tri,
                        res.get("net_est", 0.0) * 100.0,
                        res.get("realized_usdt", 0.0),
                    )
            time.sleep(0.25)
            loop_idx += 1
            # Optional Discord heartbeat during fitness
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
                            f"[fitness@{venue}] heartbeat simulate={simulate} symbols={len(syms)} "
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

    # Final end-of-run summary (console + Discord best-effort)
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


@app.command()
def live(
    venue: str = "alpaca",
    symbols: str | None = None,
    auto_suggest_top: int = 0,
    attempt_notify: bool | None = TyperOption(
        None,
        "--attempt-notify/--no-attempt-notify",
        help="Send per-attempt Discord alerts (noisy). Overrides env.",
    ),
    help_verbose: bool = False,
):
    """Continuously scan for profitable triangles and execute trades.

    Logs current account balances at startup for supported venues.
    """

    if help_verbose:
        typer.echo(
            "Log line: 'alpaca Triangle(ETH/USDT, ETH/BTC, BTC/USDT) net=0.15% PnL=0.10 USDT'\n"
            "net = estimated profit after fees; PnL = realized gain in USDT."
        )
        raise SystemExit(0)

    # Start metrics server once per process
    try:
        start_metrics_server(settings.prom_port)
    except Exception:
        pass

    # Delegate to async runner
    try:
        asyncio.run(
            _live_run_for_venue(
                venue,
                symbols=symbols,
                auto_suggest_top=auto_suggest_top,
                attempt_notify_override=attempt_notify,
            )
        )
    except KeyboardInterrupt:
        pass
    finally:
        # On shutdown, send a stop summary (best-effort)
        if bool(getattr(settings, "discord_live_stop_notify", True)):
            try:
                a = _build_adapter(venue, settings)
                notify_discord(venue, f"[live@{venue}] stop | {_balances_brief(a)}")
            except Exception:
                pass
    return
    """
        # Filter out triangles with legs not listed by the venue (defensive)
        try:
            ms = a.load_markets()
            missing: list[tuple[Triangle, list[str]]] = []
            kept: list[Triangle] = []
            for t in tris:
                legs = [t.leg_ab, t.leg_bc, t.leg_ac]
                miss = [leg for leg in legs if leg not in ms]
                if miss:
                    missing.append((t, miss))
                else:
                    kept.append(t)
            tris = kept
        except Exception:
            pass
        if not tris:
            # Try suggest triangles programmatically
            suggestions: list[list[str]] = []
            try:
                ms = a.load_markets()
                suggestions = _discover_triangles_from_markets(ms)[:3]
            except Exception:
                suggestions = []
            # If requested, auto-use top-N suggestions for this session only
            use_count = int(auto_suggest_top or 0)
            if use_count > 0 and suggestions:
                chosen = suggestions[:use_count]
                tris = [Triangle(*t) for t in chosen]
                try:
                    notify_discord(
                        venue,
                        (
                            f"[live@{venue}] using auto-suggested triangles for session: "
                            f"{'; '.join('|'.join(t) for t in chosen)}"
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
                            f"{x.leg_ab}|{x.leg_bc}|{x.leg_ac} -> missing {','.join(m)}"
                            for x, m in (missing if "missing" in locals() else [])
                        )
                        if "missing" in locals() and missing
                        else "n/a"
                    ),
                    (
                        "; ".join("|".join(t) for t in suggestions)
                        if suggestions
                        else "n/a"
                    ),
                )
                try:
                    notify_discord(
                        venue,
                        (
                            f"[live@{venue}] no supported triangles; "
                            f"suggestions={('; '.join('|'.join(t) for t in suggestions)) if suggestions else 'n/a'}"
                        ),
                    )
                except Exception:
                    pass
                return
        # Status banner: show active triangles after filtering and market check
        if tris:
            tri_list = ", ".join(f"{t.leg_ab}|{t.leg_bc}|{t.leg_ac}" for t in tris)
            log.info(
                "live@%s active triangles=%d -> %s",
                venue,
                len(tris),
                tri_list,
            )
            # Send a one-time Discord notice of active triangles for visibility
            try:
                notify_discord(
                    venue,
                    f"[live@{venue}] active triangles={len(tris)} -> {tri_list}",
                )
            except Exception:
                pass
        for tri in tris:
            insert_triangle(conn, tri)
        log.info("live@%s dry_run=%s", venue, settings.dry_run)
        # Discord notify controls
        last_alert_at = 0.0
        last_trade_notify_at = 0.0
        min_interval = float(
            getattr(settings, "discord_min_notify_interval_secs", 10) or 10
        )
        # Live start notice
        if bool(getattr(settings, "discord_live_start_notify", True)):
            try:
                notify_discord(
                    venue,
                    (
                        f"[live@{venue}] start dry_run={getattr(settings, 'dry_run', True)} "
                        f"threshold_bps={getattr(settings, 'net_threshold_bps', 0)} "
                        f"notional=${getattr(settings, 'notional_per_trade_usd', 0)} "
                        f"slippage_bps={getattr(settings, 'max_slippage_bps', 0)} "
                        f"triangles={len(tris)}"
                    ),
                )
            except Exception:
                pass
        last_hb_at = 0.0
        start_time = time.time()
        attempts_total = 0
        successes_total = 0
        latency_total = 0.0
        net_total = 0.0
        # Aggregate skip reasons for visibility in periodic summaries
        from collections import defaultdict

        skip_counts: dict[str, int] = defaultdict(int)
        for tri, res, skip_reasons, latency in []:
            attempts_total += 1
            latency_total += latency
            try:
                CYCLE_LATENCY.labels(venue).observe(latency)
            except Exception:
                pass
            # Persist attempt record
            try:
                ob_ab = a.fetch_orderbook(tri.leg_ab, 1)
                ob_bc = a.fetch_orderbook(tri.leg_bc, 1)
                ob_ac = a.fetch_orderbook(tri.leg_ac, 1)

                def _best(ob, side):
                    try:
                        arr = ob.get(side) or []
                        return arr[0][0] if arr else None
                    except Exception:
                        return None

                attempt = TriangleAttempt(
                    venue=venue,
                    leg_ab=tri.leg_ab,
                    leg_bc=tri.leg_bc,
                    leg_ac=tri.leg_ac,
                    ts_iso=datetime.now(timezone.utc).isoformat(),
                    ok=bool(res),
                    net_est=(float(res.get("net_est", 0.0)) if res else None),
                    realized_usdt=(
                        float(res.get("realized_usdt", 0.0)) if res else None
                    ),
                    threshold_bps=float(getattr(settings, "net_threshold_bps", 0.0)),
                    notional_usd=float(
                        getattr(settings, "notional_per_trade_usd", 0.0)
                    ),
                    slippage_bps=float(getattr(settings, "max_slippage_bps", 0.0)),
                    dry_run=bool(getattr(settings, "dry_run", True)),
                    latency_ms=latency * 1000.0,
                    skip_reasons=",".join(skip_reasons) if skip_reasons else None,
                    ab_bid=_best(ob_ab, "bids"),
                    ab_ask=_best(ob_ab, "asks"),
                    bc_bid=_best(ob_bc, "bids"),
                    bc_ask=_best(ob_bc, "asks"),
                    ac_bid=_best(ob_ac, "bids"),
                    ac_ask=_best(ob_ac, "asks"),
                    qty_base=(
                        float(res["fills"][0]["qty"])
                        if res and res.get("fills")
                        else None
                    ),
                )
                attempt_id = insert_attempt(conn, attempt)
            except Exception:
                attempt_id = None

            if not res:
                if skip_reasons:
                    for r in skip_reasons:
                        try:
                            SKIPS_TOTAL.labels(venue, r).inc()
                        except Exception:
                            pass
                        skip_counts[r] = skip_counts.get(r, 0) + 1
                    actionable = [
                        r
                        for r in skip_reasons
                        if r.startswith("slippage") or r.startswith("min_notional")
                    ]
                    if actionable and time.time() - last_alert_at > 10:
                        notify_discord(
                            venue,
                            f"[{venue}] skipped {tri} - reasons: {', '.join(actionable)}",
                        )
                    if (
                        actionable
                        and bool(getattr(settings, "discord_skip_notify", True))
                        and time.time() - last_alert_at > min_interval
                    ):
                        try:
                            notify_discord(
                                venue,
                                f"[{venue}] skipped {tri} reasons: {', '.join(actionable)}",
                            )
                        except Exception:
                            pass
                        last_alert_at = time.time()
                else:
                    try:
                        SKIPS_TOTAL.labels(venue, "unprofitable").inc()
                    except Exception:
                        pass
                continue
            successes_total += 1
            net_total += res["net_est"]
            PROFIT_TOTAL.labels(venue).set(res["realized_usdt"])
            ORDERS_TOTAL.labels(venue, "ok").inc()
            for f in res.get("fills", []):
                try:
                    insert_fill(
                        conn,
                        Fill(
                            order_id=str(f.get("id", "")),
                            symbol=str(f.get("symbol", "")),
                            side=str(f.get("side", "")),
                            price=float(f.get("price", 0.0)),
                            quantity=float(f.get("qty", 0.0)),
                            fee=float(f.get("fee", 0.0)),
                            timestamp=None,
                            venue=venue,
                            leg=str(f.get("leg") or ""),
                            tif=str(f.get("tif") or ""),
                            order_type=str(f.get("type") or ""),
                            fee_rate=(
                                float(f.get("fee_rate"))
                                if f.get("fee_rate") is not None
                                else None
                            ),
                            notional=float(f.get("price", 0.0))
                            * float(f.get("qty", 0.0)),
                            dry_run=bool(getattr(settings, "dry_run", True)),
                            attempt_id=attempt_id,
                        ),
                    )
                    FILLS_TOTAL.labels(venue).inc()
                except Exception as e:
                    log.error("persist fill error: %s", e)
            log.info(
                "%s %s net=%.3f%% (est. profit after fees) PnL=%.2f USDT",
                venue,
                tri,
                res["net_est"] * 100,
                res["realized_usdt"],
            )
            # Trade executed notification
            if bool(getattr(settings, "discord_trade_notify", False)) and (
                time.time() - last_trade_notify_at > min_interval
            ):
                try:
                    msg = (
                        f"[{venue}] TRADE {tri} net={res['net_est'] * 100:.2f}% "
                        f"pnl={res['realized_usdt']:.4f} USDT "
                    )
                    if attempt_id is not None:
                        msg += f"attempt_id={attempt_id} "
                    qty = (
                        float(res["fills"][0]["qty"])
                        if res and res.get("fills")
                        else None
                    )
                    if qty is not None:
                        msg += f"qty={qty:.6g} "
                    msg += f"slip_bps={getattr(settings, 'max_slippage_bps', 0)}"
                    notify_discord(venue, msg)
                except Exception:
                    pass
                last_trade_notify_at = time.time()

            # Periodic Discord heartbeat summary
            hb_interval = float(
                getattr(settings, "discord_heartbeat_secs", 60.0) or 60.0
            )
            if hb_interval > 0 and time.time() - last_hb_at > hb_interval:
                # Console heartbeat for local visibility
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
                        # Show top 3 skip reasons by count for quick diagnosis
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

    try:
        asyncio.run(
            _live_run_for_venue(
                venue, symbols=symbols, auto_suggest_top=auto_suggest_top
            )
        )
    except KeyboardInterrupt:
        pass
    finally:
        # On shutdown, send a stop summary (best-effort)
        if bool(getattr(settings, "discord_live_stop_notify", True)):
            try:
                a = _build_adapter(venue, settings)
                notify_discord(venue, f"[live@{venue}] stop | {_balances_brief(a)}")
            except Exception:
                pass

    """


@app.command("live:multi")
@app.command("live_multi")
def live_multi(
    venues: str | None = None,
    symbols: str | None = None,
    auto_suggest_top: int = 0,
    attempt_notify: bool | None = TyperOption(
        None,
        "--attempt-notify/--no-attempt-notify",
        help="Send per-attempt Discord alerts (noisy). Overrides env.",
    ),
    help_verbose: bool = False,
):
    """Run live trading loops concurrently across multiple venues.

    Provide a CSV via --venues (default: settings.exchanges). Uses same flags as `live` per venue.
    """

    if help_verbose:
        typer.echo(
            "Runs multiple venue loops concurrently. Example:\n"
            "  python -m arbit.cli live:multi --venues alpaca,kraken\n"
            "Flags: --symbols, --auto-suggest-top mirror `live` and apply per venue."
        )
        raise SystemExit(0)

    vlist = [
        v.strip()
        for v in (venues or ",".join(settings.exchanges)).split(",")
        if v.strip()
    ] or ["alpaca", "kraken"]

    # Start metrics server once per process
    try:
        start_metrics_server(settings.prom_port)
    except Exception:
        pass

    async def _run_all():
        tasks = [
            asyncio.create_task(
                _live_run_for_venue(
                    v,
                    symbols=symbols,
                    auto_suggest_top=auto_suggest_top,
                    attempt_notify_override=attempt_notify,
                )
            )
            for v in vlist
        ]
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:  # pragma: no cover - ctrl+c handling
            for t in tasks:
                t.cancel()
        except KeyboardInterrupt:  # pragma: no cover
            for t in tasks:
                t.cancel()

    try:
        asyncio.run(_run_all())
    except KeyboardInterrupt:
        pass
    finally:
        if bool(getattr(settings, "discord_live_stop_notify", True)):
            for v in vlist:
                try:
                    a = _build_adapter(v, settings)
                    notify_discord(v, f"[live@{v}] stop | {_balances_brief(a)}")
                except Exception:
                    pass


if __name__ == "__main__":
    app()
