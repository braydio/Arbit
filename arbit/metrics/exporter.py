"""Prometheus metrics collectors and helpers.

This module exposes counters and gauges for tracking orders and profit as well as
utilities for starting the metrics HTTP server.
"""

from prometheus_client import Counter, Gauge, start_http_server

# Metric collectors
ORDERS_TOTAL = Counter("orders_total", "Total orders processed", ["venue", "result"])
PROFIT_TOTAL = Gauge("profit_total_usdt", "Realized profit in USDT", ["venue"])


def start_metrics_server(port: int) -> None:
    """Start the Prometheus metrics server on the provided ``port``.

    Parameters
    ----------
    port:
        TCP port to bind the HTTP server to.
    """

    start_http_server(port)
