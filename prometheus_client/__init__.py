"""Minimal Prometheus client stub for tests.

This module provides a tiny subset of the :mod:`prometheus_client` API used by
the project.  The real dependency is quite heavy, so the test suite ships this
lightweight stand‑in instead.  The ``Counter`` and ``Gauge`` classes simply
track a numeric value, and :func:`start_http_server` spins up a background HTTP
server that responds to ``GET`` requests with an empty body.
"""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class _Value:
    """Container for a single numeric metric value."""

    def __init__(self) -> None:
        self._v = 0.0

    def get(self) -> float:
        return self._v


class _Metric:
    """Simple metric supporting ``inc`` and ``set`` operations."""

    def __init__(self, *args, **kwargs) -> None:  # pragma: no cover - trivial
        self._value = _Value()

    def inc(self, amount: float = 1.0) -> None:  # pragma: no cover - trivial
        self._value._v += amount

    def set(self, value: float) -> None:  # pragma: no cover - trivial
        self._value._v = value


Counter = Gauge = _Metric


class _Handler(BaseHTTPRequestHandler):
    """Trivial HTTP handler returning an empty 200 response."""

    def do_GET(self) -> None:  # pragma: no cover - trivial
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()

    def log_message(self, *_args, **_kwargs) -> None:  # pragma: no cover - quiet
        pass


def start_http_server(port: int) -> None:
    """Start a background HTTP server listening on ``port``.

    The server is intentionally minimal – it merely keeps the port occupied and
    responds to requests with a successful status.  This mirrors the behaviour
    of the real Prometheus client's ``start_http_server`` function sufficiently
    for tests that expect the call to succeed.
    """

    server = HTTPServer(("", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    return None
