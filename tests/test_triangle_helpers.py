"""Helper function tests for triangular arbitrage calculations."""

import pytest

from arbit.engine.triangle import net_edge_cycle, size_from_depth, top


def test_top() -> None:
    """Best bid/ask pair is returned and empty lists yield ``(None, None)``."""
    levels = [(1.0, 2.0), (0.9, 2.1)]
    assert top(levels) == (1.0, 2.0)
    assert top([]) == (None, None)


def test_net_edge_cycle() -> None:
    """Net edge multiplies each rate and subtracts one."""
    assert net_edge_cycle([1.0, 1.1, 1.2]) == pytest.approx(0.32)


def test_size_from_depth() -> None:
    """Smallest quantity across levels determines executable size."""
    levels = [(10.0, 20.0), (11.0, 5.0)]
    assert size_from_depth(levels) == 5.0
    assert size_from_depth([]) == 0.0
