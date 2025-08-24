import pytest

from arbit.engine.triangle import net_edge, size_from_depth, top


def test_top() -> None:
    ob = {"bids": [(1.0, 2.0), (0.9, 1.0)], "asks": [(2.0, 3.0), (2.1, 1.0)]}
    assert top(ob) == (1.0, 2.0)
    assert top({"bids": [], "asks": []}) == (None, None)


def test_net_edge() -> None:
    assert net_edge(1.0, 1.1, 1.2, 0.0) == pytest.approx(0.32)


def test_size_from_depth() -> None:
    assert size_from_depth(100.0, 10.0, 20.0) == 10.0
    assert size_from_depth(100.0, 0.0, 20.0) == 0.0
