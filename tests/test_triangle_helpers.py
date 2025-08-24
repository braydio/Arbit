import pytest

from arbit.engine.triangle import net_edge_cycle, size_from_depth, top


def test_top() -> None:
    assert top([(1.0, 2.0), (0.9, 1.0)]) == (1.0, 2.0)
    assert top([]) == (0.0, 0.0)


def test_net_edge_cycle() -> None:
    assert net_edge_cycle([1.1, 1.2]) == pytest.approx(0.32)


def test_size_from_depth() -> None:
    levels = [(1.0, 5.0), (2.0, 3.0), (3.0, 4.0)]
    assert size_from_depth(levels) == 3.0
    assert size_from_depth([]) == 0.0
