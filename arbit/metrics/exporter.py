"""Prometheus metrics collectors and helpers.

This module exposes counters and gauges for tracking orders and profit as well as
utilities for starting the metrics HTTP server.
"""

from prometheus_client import Counter, Gauge, Histogram, start_http_server

# Metric collectors
ORDERS_TOTAL = Counter("orders_total", "Total orders processed", ["venue", "result"])
FILLS_TOTAL = Counter("fills_total", "Total fills recorded", ["venue"])
PROFIT_TOTAL = Gauge("profit_total_usdt", "Realized profit in USDT", ["venue"])
ERRORS_TOTAL = Counter("errors_total", "Total errors encountered", ["venue", "stage"])
SKIPS_TOTAL = Counter("skips_total", "Total cycles skipped", ["venue", "reason"])
CYCLE_LATENCY = Histogram(
    "cycle_latency_seconds",
    "Per-triangle processing latency in seconds",
    ["venue"],
)


def start_metrics_server(port: int) -> None:
    """Start the Prometheus metrics server on the provided ``port``.

    Parameters
    ----------
    port:
        TCP port to bind the HTTP server to.
    """

    # Be tolerant of env-sourced strings like "9109".
    start_http_server(int(port))
