"""Tests for triangle utility helpers."""

from arbit.engine.triangle import size_from_depth


def test_size_from_depth_uses_smallest_quantity() -> None:
    """Return the minimum quantity across all levels."""
    levels = [(1.0, 5.0), (2.0, 3.0), (3.0, 4.0)]
    assert size_from_depth(levels) == 3.0


def test_size_from_depth_empty_levels() -> None:
    """Empty levels should result in zero executable size."""
    assert size_from_depth([]) == 0.0
