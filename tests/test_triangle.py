"""Tests for triangle utility helpers."""

import pytest
import sys
import types

sys.modules["arbit.config"] = types.SimpleNamespace(
    settings=types.SimpleNamespace(
        notional_per_trade_usd=200.0,
        net_threshold_bps=10.0,
        dry_run=True,
        prom_port=9109,
        log_level="INFO",
    )
)

from arbit.engine.triangle import size_from_depth


def test_size_from_depth_uses_smallest_quantity() -> None:
    """Return the minimum quantity considering notional and depth."""
    assert size_from_depth(100.0, 10.0, 5.0) == pytest.approx(4.5)


def test_size_from_depth_empty_levels() -> None:
    """Zero price or quantity yields zero executable size."""
    assert size_from_depth(100.0, 0.0, 0.0) == 0.0
