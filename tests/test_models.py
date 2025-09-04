"""Basic dataclass model tests."""

from arbit.models import Fill, OrderSpec, Triangle


def test_triangle() -> None:
    """Triangle dataclass exposes configured legs."""
    tri = Triangle("ETH/USDT", "ETH/BTC", "BTC/USDT")
    assert tri.leg_ab == "ETH/USDT"
    assert tri.leg_bc == "ETH/BTC"
    assert tri.leg_ac == "BTC/USDT"


def test_order_spec() -> None:
    """OrderSpec defaults to a limit order without price."""
    order = OrderSpec(symbol="ETH/USDT", side="buy", quantity=1.0)
    assert order.order_type == "limit"
    assert order.price is None


def test_fill() -> None:
    """Fill captures execution details from an order."""
    fill = Fill(
        order_id="1", symbol="ETH/USDT", side="buy", price=10.0, quantity=1.0, fee=0.1
    )
    assert fill.order_id == "1"
    assert fill.fee == 0.1
