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
ORDERBOOK_STALENESS = Histogram(
    "orderbook_staleness_seconds",
    "Time between subsequent order book updates (per venue)",
    ["venue"],
)

# Yield metrics
YIELD_DEPOSITS_TOTAL = Counter(
    "yield_deposits_total", "Total yield deposits executed", ["provider", "mode"]
)
YIELD_WITHDRAWS_TOTAL = Counter(
    "yield_withdraws_total", "Total yield withdrawals executed", ["provider", "mode"]
)
YIELD_ERRORS_TOTAL = Counter("yield_errors_total", "Yield-related errors", ["stage"])
YIELD_CAPITAL_USD = Gauge(
    "yield_capital_usd", "Capital allocated to yield in USD", ["provider"]
)
YIELD_APR = Gauge("yield_apr_percent", "Provider APR (percent)", ["provider", "asset"])
YIELD_BEST_APR = Gauge(
    "yield_best_apr_percent", "Best APR observed across sources (percent)", ["asset"]
)
YIELD_CHECKS_TOTAL = Counter(
    "yield_checks_total", "Scheduled yield rate checks executed"
)
YIELD_ALERTS_TOTAL = Counter(
    "yield_alerts_total", "Alerts triggered for better yield", ["asset"]
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
