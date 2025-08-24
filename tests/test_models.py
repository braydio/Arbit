from arbit.models import Triangle, OrderSpec, Fill


def test_triangle() -> None:
    tri = Triangle("ETH/USDT", "BTC/ETH", "BTC/USDT")
    assert tri.leg_ab == "ETH/USDT"
    assert tri.leg_bc == "BTC/ETH"
    assert tri.leg_ac == "BTC/USDT"


def test_order_spec() -> None:
    order = OrderSpec(symbol="ETH/USDT", side="buy", quantity=1.0)
    assert order.order_type == "limit"
    assert order.price is None


def test_fill() -> None:
    fill = Fill(
        order_id="1", symbol="ETH/USDT", side="buy", price=10.0, quantity=1.0, fee=0.1
    )
    assert fill.order_id == "1"
    assert fill.fee == 0.1
