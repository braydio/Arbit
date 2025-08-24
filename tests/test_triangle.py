"""Tests for triangle utility helpers."""

import pytest

from arbit.engine.triangle import size_from_depth


def test_size_from_depth_uses_smallest_quantity() -> None:
    """Return the minimum quantity across all levels."""
    levels = [(10.0, 5.0), (11.0, 4.5)]
    assert size_from_depth(levels) == pytest.approx(4.5)


def test_size_from_depth_empty_levels() -> None:
    """Empty order book yields zero executable size."""
    assert size_from_depth([]) == 0.0
