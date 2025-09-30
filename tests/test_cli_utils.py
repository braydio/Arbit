"""Tests for CLI utility helpers."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace


class _MetricStub:
    """Minimal stand-in for Prometheus metrics used in tests."""

    def __call__(self, *args, **kwargs):  # pragma: no cover - defensive stub
        return self

    def labels(self, *args, **kwargs):  # pragma: no cover - defensive stub
        return self

    def observe(self, *args, **kwargs):  # pragma: no cover - defensive stub
        return None

    def inc(self, *args, **kwargs):  # pragma: no cover - defensive stub
        return None

    def set(self, *args, **kwargs):  # pragma: no cover - defensive stub
        return None


if "prometheus_client" not in sys.modules:
    prometheus_stub = ModuleType("prometheus_client")
    metric_stub = _MetricStub()
    prometheus_stub.Counter = prometheus_stub.Gauge = prometheus_stub.Histogram = (
        lambda *args, **kwargs: metric_stub
    )

    def _start_http_server_stub(*_args, **_kwargs):  # pragma: no cover - stub
        return None

    prometheus_stub.start_http_server = _start_http_server_stub
    sys.modules["prometheus_client"] = prometheus_stub


from arbit.cli import utils as cli_utils
from arbit.models import Triangle


def test_triangles_for_respects_explicit_empty_list(monkeypatch) -> None:
    """An explicit empty list should disable fallback defaults."""

    monkeypatch.setattr(
        cli_utils,
        "settings",
        SimpleNamespace(triangles_by_venue={"alpaca": []}),
    )

    assert cli_utils._triangles_for("alpaca") == []


def test_triangles_for_default_settings_include_alpaca_sol_triangle() -> None:
    """Default configuration seeds Alpaca with the SOL/BTC/USD triangle."""

    triangles = cli_utils._triangles_for("alpaca")

    assert triangles
    assert (triangles[0].leg_ab, triangles[0].leg_bc, triangles[0].leg_ac) == (
        "SOL/USD",
        "SOL/BTC",
        "BTC/USD",
    )


def test_triangles_for_missing_venue_uses_fallback(monkeypatch) -> None:
    """Missing venue definitions should still return the default templates."""

    monkeypatch.setattr(
        cli_utils,
        "settings",
        SimpleNamespace(triangles_by_venue={}),
    )

    triangles = cli_utils._triangles_for("kraken")

    assert triangles  # default fallback templates
    assert all(isinstance(tri, Triangle) for tri in triangles)
    assert triangles[0].leg_ab == "ETH/USDT"
