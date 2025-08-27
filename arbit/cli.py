"""Command line interface utilities.

This module exposes Typer-based commands for interacting with the
arbitrage engine.  Helper functions for metrics and persistence are
imported here so tests can easily monkeypatch them.
"""

import logging
import sys
import time

import typer
from arbit import try_triangle
from arbit.adapters.ccxt_adapter import CcxtAdapter
from arbit.config import settings
from arbit.metrics.exporter import ORDERS_TOTAL, PROFIT_TOTAL, start_metrics_server
from arbit.models import Triangle
from arbit.persistence.db import init_db, insert_triangle


class CLIApp(typer.Typer):
    """Custom Typer application that prints usage on bad invocation."""

    def main(self, args: list[str] | None = None):
        """Run the CLI with *args*, showing usage on invalid input."""
        if args is None:
            args = sys.argv[1:]
        if not args or args[0] not in self.commands:
            typer.echo("Usage: arbit.cli [COMMAND]")
            if self.commands:
                typer.echo("Commands:")
                for name in sorted(self.commands):
                    typer.echo(f"  {name}")
            raise SystemExit(0 if not args else 1)
        return super().main(args)


app = CLIApp()
log = logging.getLogger("arbit")
logging.basicConfig(level=settings.log_level)

TRIS = [
    Triangle("ETH/USDT", "BTC/ETH", "BTC/USDT"),
    Triangle("ETH/USDC", "BTC/ETH", "BTC/USDC"),
]


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
                else "BTC/USD" if "BTC/USD" in ms else next(iter(ms))
            )
            ob = a.fetch_orderbook(symbol, 1)
            bid = ob.get("bids", [])
            ask = ob.get("asks", [])
            bid_price = bid[0][0] if bid else "n/a"
            ask_price = ask[0][0] if ask else "n/a"
            log.info(f"[{venue}] markets={len(ms)} {symbol} {bid_price}/{ask_price}")
        except Exception as e:
            log.error(f"[{venue}] ERROR: {e}")


@app.command()
def fitness(venue: str = "alpaca", secs: int = 20):
    a = _build_adapter(venue, settings)
    t0 = time.time()
    syms = {s for t in TRIS for s in (t.leg_ab, t.leg_bc, t.leg_ac)}
    while time.time() - t0 < secs:
        for s in syms:
            ob = a.fetch_orderbook(s, 5)
            if ob["bids"] and ob["asks"]:
                spread = (
                    (ob["asks"][0][0] - ob["bids"][0][0]) / ob["asks"][0][0]
                ) * 1e4
                log.info(f"{venue} {s} spread={spread:.1f} bps")
        time.sleep(0.25)


@app.command()
def live(venue: str = "alpaca"):
    """Continuously scan for profitable triangles and execute trades."""
    a = _build_adapter(venue, settings)
    start_metrics_server(settings.prom_port)
    conn = init_db(settings.sqlite_path)
    for tri in TRIS:
        insert_triangle(conn, tri)
    log.info(f"live@{venue} dry_run={settings.dry_run}")
    while True:
        for tri in TRIS:
            books = {
                tri.leg_ab: a.fetch_orderbook(tri.leg_ab, 10),
                tri.leg_bc: a.fetch_orderbook(tri.leg_bc, 10),
                tri.leg_ac: a.fetch_orderbook(tri.leg_ac, 10),
            }
            res = try_triangle(
                a,
                tri,
                books,
                settings.net_threshold_bps / 10000.0,
            )
            if not res:
                continue
            PROFIT_TOTAL.labels(venue).set(res["realized_usdt"])
            ORDERS_TOTAL.labels(venue, "ok").inc()
            log.info(
                f"{venue} {tri} net={res['net_est']:.3%} PnL={res['realized_usdt']:.2f} USDT"
            )
        time.sleep(0.05)


if __name__ == "__main__":
    app()
