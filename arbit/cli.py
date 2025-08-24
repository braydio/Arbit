"""Command line interface for running the arbitrage engine."""

import logging
import time

import typer
from arbit.adapters.ccxt_adapter import CcxtAdapter
from arbit.config import settings
from arbit.engine.executor import try_triangle
from arbit.engine.triangle import Triangle
from arbit.metrics.exporter import arb_cycles, pnl_gross
from arbit.metrics.exporter import start as prom_start

app = typer.Typer()
log = logging.getLogger("arbit")
logging.basicConfig(level=settings.log_level)

TRIS = [
    Triangle("ETH/USDT", "BTC/ETH", "BTC/USDT"),
    Triangle("ETH/USDC", "BTC/ETH", "BTC/USDC"),
]


def make(venue: str):
    return CcxtAdapter(venue)


@app.command("keys:check")
def keys_check():
    for venue in settings.exchanges:
        try:
            a = make(venue)
            ms = a.ex.load_markets()
            ob = a.fetch_orderbook("BTC/USDT", 1)
            log.info(
                f"[{venue}] markets={len(ms)} BTC/USDT {ob['bids'][0][0]}/{ob['asks'][0][0]}"
            )
        except Exception as e:
            log.error(f"[{venue}] ERROR: {e}")


@app.command()
def fitness(venue: str = "alpaca", secs: int = 20):
    a = make(venue)
    t0 = time.time()
    syms = {s for t in TRIS for s in (t.AB, t.BC, t.AC)}
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
    a = make(venue)
    prom_start(settings.prom_port)
    log.info(f"live@{venue} dry_run={settings.dry_run}")
    while True:
        for tri in TRIS:
            books = {
                tri.AB: a.fetch_orderbook(tri.AB, 10),
                tri.BC: a.fetch_orderbook(tri.BC, 10),
                tri.AC: a.fetch_orderbook(tri.AC, 10),
            }
            res = try_triangle(
                a,
                tri,
                books,
                settings.net_threshold_bps / 10000.0,
            )
            if not res:
                continue
            pnl_gross.labels(venue).set(res["realized_usdt"])
            arb_cycles.labels(venue, "ok").inc()
            log.info(
                f"{venue} {tri} net={res['net_est']:.3%} PnL={res['realized_usdt']:.2f} USDT"
            )
        time.sleep(0.05)


if __name__ == "__main__":
    app()
