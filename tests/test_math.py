"""Tests for mathematical helper functions."""

import pytest

from arbit.engine.triangle import net_edge_cycle


def test_net_edge_cycle_product_minus_one() -> None:
    """Net edge multiplies edges and subtracts one."""
    assert net_edge_cycle([1.0, 1.1, 1.2]) == pytest.approx(0.32)


def test_net_edge_cycle_no_profit() -> None:
    """Neutral edges should yield zero net edge."""
    assert net_edge_cycle([1.0, 1.0, 1.0]) == 0.0
