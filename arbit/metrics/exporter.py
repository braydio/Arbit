"""Prometheus metrics exporter and helpers."""

from __future__ import annotations

from prometheus_client import Counter, Gauge, start_http_server

# Counters
ORDERS_TOTAL = Counter("orders_total", "Total number of orders placed")
FILLS_TOTAL = Counter("fills_total", "Total number of fills recorded")

# Gauges
PROFIT_TOTAL = Gauge("profit_total", "Accumulated profit in quote currency")


def start_metrics_server(port: int = 8000) -> None:
    """Start an HTTP server exposing Prometheus metrics."""
    start_http_server(port)

