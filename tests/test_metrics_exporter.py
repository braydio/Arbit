import pytest

pytest.importorskip("prometheus_client")

from arbit.metrics import exporter


def test_metrics_counters_and_gauge():
    exporter.ORDERS_TOTAL.inc()
    exporter.PROFIT_TOTAL.set(5.0)
    exporter.start_metrics_server(8001)
    assert exporter.ORDERS_TOTAL._value.get() == 1.0
    assert exporter.PROFIT_TOTAL._value.get() == 5.0
