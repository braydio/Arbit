"""Typer-based command-line interface for Arbit.

Provides ``fitness`` and ``live`` subcommands to exercise the trading
components in isolation or in a simplified live loop.
"""

from __future__ import annotations

import time

import typer

from .config import Settings
from .engine.executor import try_triangle
from .engine.triangle import net_edge_cycle, top
from .metrics.exporter import ORDERS_TOTAL, start_metrics_server
from .models import Triangle
from .persistence.db import init_db, insert_triangle

app = typer.Typer()

# Default trading triangle for USDT→ETH→BTC→USDT
DEFAULT_TRIANGLE = Triangle("ETH/USDT", "BTC/ETH", "BTC/USDT")


def _build_adapter(venue: str, settings: Settings):
    """Return a CCXT adapter configured for *venue*."""
    from .adapters.ccxt_adapter import CCXTAdapter
    return CCXTAdapter(venue, settings.api_key, settings.api_secret)


@app.command()
def fitness(venue: str = "alpaca", secs: int = 20) -> None:
    """Run a short connectivity test against *venue*.

    The command fetches order books for a predefined triangle once per
    second and prints the estimated net return.  It repeats for *secs*
    iterations.
    """

    settings = Settings()
    adapter = _build_adapter(venue, settings)
    triangle = DEFAULT_TRIANGLE

    for _ in range(secs):
        ob_ab = adapter.fetch_order_book(triangle.leg_ab)
        ob_bc = adapter.fetch_order_book(triangle.leg_bc)
        ob_ac = adapter.fetch_order_book(triangle.leg_ac)

        ab = top(ob_ab.get("asks", []))
        bc = top(ob_bc.get("bids", []))
        ac = top(ob_ac.get("bids", []))

        net = net_edge_cycle([1 / ab[0] if ab[0] else 0.0, bc[0], ac[0]])
        typer.echo(f"net={net:.4%}")
        time.sleep(1)


@app.command()
def live(venue: str = "alpaca", cycles: int = 1, metrics_port: int = 8000) -> None:
    """Execute a simplified live trading loop.

    The command initialises the database and metrics exporter before
    fetching order books and attempting to trade using
    :func:`~arbit.engine.executor.try_triangle`.
    """

    settings = Settings()
    adapter = _build_adapter(venue, settings)
    conn = init_db(str(settings.data_dir / "arbit.db"))
    start_metrics_server(metrics_port)

    triangle = DEFAULT_TRIANGLE
    insert_triangle(conn, triangle)

    for _ in range(cycles):
        order_books = {
            triangle.leg_ab: adapter.fetch_order_book(triangle.leg_ab),
            triangle.leg_bc: adapter.fetch_order_book(triangle.leg_bc),
            triangle.leg_ac: adapter.fetch_order_book(triangle.leg_ac),
        }
        if try_triangle(adapter, triangle, order_books, settings.net_threshold):
            ORDERS_TOTAL.inc(3)
        time.sleep(1)


def main() -> None:
    """Entry point for ``python -m arbit.cli``."""
    app()


if __name__ == "__main__":  # pragma: no cover - manual invocation
    main()
