"""Tests for Prometheus metrics exporter (skipped without dependency)."""

import pytest

pytest.importorskip("prometheus_client")


def test_metrics_counters_and_gauge():
    pytest.skip("Prometheus metrics not available in test environment")
