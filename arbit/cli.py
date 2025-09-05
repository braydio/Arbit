"""Command line interface utilities.

This module exposes Typer-based commands for interacting with the
arbitrage engine.  Helper functions for metrics and persistence are
imported here so tests can easily monkeypatch them.
"""

import json
import logging
import sys
import time
import urllib.error
import urllib.request

import typer
from arbit import try_triangle
from arbit.adapters.ccxt_adapter import CCXTAdapter
from arbit.config import settings
from arbit.metrics.exporter import (
    CYCLE_LATENCY,
    ERRORS_TOTAL,
    FILLS_TOTAL,
    ORDERS_TOTAL,
    PROFIT_TOTAL,
    SKIPS_TOTAL,
    start_metrics_server,
)
from arbit.models import Fill, Triangle
from arbit.persistence.db import init_db, insert_fill, insert_triangle


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

        typer.echo("Available commands:")
        for cname, info in sorted(self._unique_commands().items()):
            desc = (info["command"].callback.__doc__ or "").strip().splitlines()[0]
            aliases = [
                a.replace("_", ":")
                for a in info["aliases"]
                if a.replace("_", ":") != cname
            ]
            alias_str = f" (aliases: {', '.join(sorted(aliases))})" if aliases else ""
            typer.echo(f"  {cname:<12} {desc}{alias_str}")

    # ------------------------------------------------------------------
    @staticmethod
    def _print_verbose_help() -> None:
        """Print detailed command reference with flags and examples."""

        typer.echo("Command reference:\n")

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
            "  Sample output:\n"
            "    alpaca ETH/USDT spread=10.0 bps\n"
            "    alpaca [sim] Triangle(ETH/USDT, ETH/BTC, BTC/USDT) net=0.15% PnL=0.05 USDT\n"
        )

        typer.echo(
            "live\n"
            "  Continuously scan for profitable triangles and execute trades.\n"
            "  Flags (optional):\n"
            "    --venue TEXT   Exchange to trade on (default: alpaca)\n"
            "  Sample output:\n"
            "    alpaca ETH/BTC net=0.5% PnL=0.10 USDT\n"
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


app = CLIApp()
log = logging.getLogger("arbit")
logging.basicConfig(level=settings.log_level)


def _triangles_for(venue: str) -> list[Triangle]:
    data = getattr(settings, "triangles_by_venue", {}) or {}
    triples = data.get(venue)
    if not triples:
        # Fallback defaults if config missing or tests stub settings
        triples = [
            ["ETH/USDT", "BTC/ETH", "BTC/USDT"],
            ["ETH/USDC", "BTC/ETH", "BTC/USDC"],
        ]
    return [Triangle(*t) for t in triples]


def _build_adapter(venue: str, _settings=settings):
    """Factory for constructing exchange adapters.

    Parameters
    ----------
    venue:
        Exchange identifier understood by the underlying adapter.
    _settings:
        Settings object used to configure the adapter (unused for now).
    """

    return CCXTAdapter(venue)


def _notify_discord(venue: str, message: str) -> None:
    """Send a simple message to Discord webhook if configured.

    Errors are swallowed; this is best-effort only.
    """
    url = settings.discord_webhook_url
    if not url:
        return
    data = json.dumps({"content": message}).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as _:
            return
    except Exception:
        # Avoid spamming logs; bump an error metric instead
        try:
            ERRORS_TOTAL.labels(venue, "discord_send").inc()
        except Exception:
            pass


@app.command("keys:check")
@app.command("keys_check")
def keys_check():
    """Validate exchange credentials by fetching a sample order book."""
    for venue in settings.exchanges:
        try:
            a = _build_adapter(venue, settings)
            ms = a.ex.load_markets()
            symbol = (
                "BTC/USDT"
                if "BTC/USDT" in ms
                else "BTC/USD"
                if "BTC/USD" in ms
                else next(iter(ms))
            )
            ob = a.fetch_orderbook(symbol, 1)
            bid = ob.get("bids", [])
            ask = ob.get("asks", [])
            bid_price = bid[0][0] if bid else "n/a"
            ask_price = ask[0][0] if ask else "n/a"
            log.info(
                "[%s] markets=%d %s %s/%s",
                venue,
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
        ms = a.ex.load_markets()
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


@app.command()
def fitness(
    venue: str = "alpaca",
    secs: int = 20,
    simulate: bool = False,
    persist: bool = False,
    help_verbose: bool = False,
):
    """Read-only sanity check that prints bid/ask spreads.

    When ``--simulate`` is provided, attempt dry-run triangle executions using
    current order books and log simulated PnL. Use ``--persist`` to store
    simulated fills in SQLite for later analysis.
    """

    if help_verbose:
        typer.echo(
            "Typical log line: 'kraken ETH/USDT spread=0.5 bps' where spread is the\n"
            "bid/ask gap expressed in basis points (1/100th of a percent)."
        )
        raise SystemExit(0)

    a = _build_adapter(venue, settings)
    tris = _triangles_for(venue)
    t0 = time.time()
    syms = {s for t in tris for s in (t.leg_ab, t.leg_bc, t.leg_ac)}

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
    try:
        while time.time() - t0 < secs:
            books_cache: dict[str, dict] = {}
            # Spread sampling per symbol
            for s in syms:
                ob = a.fetch_orderbook(s, 5)
                books_cache[s] = ob
                if ob.get("bids") and ob.get("asks"):
                    spread = (
                        (ob["asks"][0][0] - ob["bids"][0][0]) / ob["asks"][0][0]
                    ) * 1e4  # bid/ask gap in basis points
                    log.info("%s %s spread=%.1f bps (ask-bid gap)", venue, s, spread)

            # Optional: try triangles in dry-run and log/persist
            if simulate:
                for tri in tris:
                    skip_reasons: list[str] = []
                    try:
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
                    if not res:
                        # Count skips by reason (no metrics emission in fitness)
                        continue
                    sim_count += 1
                    sim_pnl += float(res.get("realized_usdt", 0.0))
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
            "%s [sim] summary: trades=%d total_pnl=%.2f USDT",
            venue,
            sim_count,
            sim_pnl,
        )


@app.command()
def live(
    venue: str = "alpaca",
    help_verbose: bool = False,
):
    """Continuously scan for profitable triangles and execute trades."""

    if help_verbose:
        typer.echo(
            "Log line: 'alpaca Triangle(ETH/USDT, ETH/BTC, BTC/USDT) net=0.15% PnL=0.10 USDT'\n"
            "net = estimated profit after fees; PnL = realized gain in USDT."
        )
        raise SystemExit(0)

    a = _build_adapter(venue, settings)
    start_metrics_server(settings.prom_port)
    conn = init_db(settings.sqlite_path)
    tris = _triangles_for(venue)
    for tri in tris:
        insert_triangle(conn, tri)
    log.info("live@%s dry_run=%s", venue, settings.dry_run)
    last_alert_at = 0.0
    while True:
        for tri in tris:
            t0 = time.time()
            try:
                books = {
                    tri.leg_ab: a.fetch_orderbook(tri.leg_ab, 10),
                    tri.leg_bc: a.fetch_orderbook(tri.leg_bc, 10),
                    tri.leg_ac: a.fetch_orderbook(tri.leg_ac, 10),
                }
            except Exception as e:
                ERRORS_TOTAL.labels(venue, "fetch_orderbook").inc()
                log.error("fetch_orderbook error: %s", e)
                continue
            res = try_triangle(
                a,
                tri,
                books,
                settings.net_threshold_bps / 10000.0,
                skip_reasons := [],
            )
            # Record latency per-triangle
            try:
                CYCLE_LATENCY.labels(venue).observe(max(time.time() - t0, 0.0))
            except Exception:
                pass
            if not res:
                # Count skips by reason (default to 'unprofitable' if none)
                if skip_reasons:
                    for r in skip_reasons:
                        try:
                            SKIPS_TOTAL.labels(venue, r).inc()
                        except Exception:
                            pass
                    # Alert on actionable skips (slippage/min_notional) with cooldown
                    actionable = [
                        r
                        for r in skip_reasons
                        if r.startswith("slippage") or r.startswith("min_notional")
                    ]
                    if actionable and time.time() - last_alert_at > 10:
                        _notify_discord(
                            venue,
                            f"[{venue}] skipped {tri} reasons: {', '.join(actionable)}",
                        )
                        last_alert_at = time.time()
                else:
                    try:
                        SKIPS_TOTAL.labels(venue, "unprofitable").inc()
                    except Exception:
                        pass
                continue
            PROFIT_TOTAL.labels(venue).set(res["realized_usdt"])
            ORDERS_TOTAL.labels(venue, "ok").inc()
            # Persist fills and update fills metric
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
        time.sleep(0.05)


if __name__ == "__main__":
    app()
