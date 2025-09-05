"""Command line interface utilities.

This module exposes Typer-based commands for interacting with the
arbitrage engine.  Helper functions for metrics and persistence are
imported here so tests can easily monkeypatch them.
"""

import asyncio
import json
import logging
import sys
import time
import urllib.error
import urllib.request

import typer
from arbit.adapters.ccxt_adapter import CcxtAdapter
from arbit.config import settings
from arbit.engine.executor import stream_triangles
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
                for name in sorted(self.commands):
                    typer.echo(f"  {name.replace('_', ':')}")
            raise SystemExit(0 if not args else 1)
        return super().main(args)

    # ------------------------------------------------------------------
    def _print_basic_help(self) -> None:
        """Print a short summary of available commands."""

        typer.echo("Available commands:")
        for name, command in sorted(self.commands.items()):
            desc = (command.callback.__doc__ or "").strip().splitlines()[0]
            typer.echo(f"  {name.replace('_', ':'):<12} {desc}")

    # ------------------------------------------------------------------
    @staticmethod
    def _print_verbose_help() -> None:
        """Print detailed command reference with flags and examples."""

        typer.echo("Command reference:\n")

        typer.echo(
            "keys:check\n"
            "  Validate exchange credentials by fetching a sample order book.\n"
            "  Sample output:\n"
            "    [alpaca] markets=123 BTC/USDT 60000/60010\n"
        )

        typer.echo(
            "fitness\n"
            "  Monitor order books to gauge spread without trading.\n"
            "  Flags:\n"
            "    --venue TEXT   Exchange to query (default: alpaca)\n"
            "    --secs INTEGER Seconds to run (default: 20)\n"
            "  Sample output:\n"
            "    alpaca ETH/USDT spread=10.0 bps\n"
        )

        typer.echo(
            "live\n"
            "  Continuously scan for profitable triangles and execute trades.\n"
            "  Flags:\n"
            "    --venue TEXT   Exchange to trade on (default: alpaca)\n"
            "  Sample output:\n"
            "    alpaca ETH/BTC net=0.5% PnL=0.10 USDT\n"
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

    return CcxtAdapter(venue)


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


@app.command()
def fitness(
    venue: str = "alpaca",
    secs: int = 20,
    help_verbose: bool = False,
):
    """Read-only sanity check that prints bid/ask spreads."""

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
    while time.time() - t0 < secs:
        for s in syms:
            ob = a.fetch_orderbook(s, 5)
            if ob["bids"] and ob["asks"]:
                spread = (
                    (ob["asks"][0][0] - ob["bids"][0][0]) / ob["asks"][0][0]
                ) * 1e4  # bid/ask gap in basis points
                log.info("%s %s spread=%.1f bps (ask-bid gap)", venue, s, spread)
        time.sleep(0.25)


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

    async def _run() -> None:
        a = _build_adapter(venue, settings)
        start_metrics_server(settings.prom_port)
        conn = init_db(settings.sqlite_path)
        tris = _triangles_for(venue)
        for tri in tris:
            insert_triangle(conn, tri)
        log.info("live@%s dry_run=%s", venue, settings.dry_run)
        last_alert_at = 0.0
        async for tri, res, skip_reasons, latency in stream_triangles(
            a, tris, settings.net_threshold_bps / 10000.0
        ):
            try:
                CYCLE_LATENCY.labels(venue).observe(latency)
            except Exception:
                pass
            if not res:
                if skip_reasons:
                    for r in skip_reasons:
                        try:
                            SKIPS_TOTAL.labels(venue, r).inc()
                        except Exception:
                            pass
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

    asyncio.run(_run())


if __name__ == "__main__":
    app()
