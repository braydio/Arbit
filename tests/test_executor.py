from arbit.engine.executor import try_triangle
from arbit.models import Triangle, OrderSpec, Fill
from arbit.adapters.base import ExchangeAdapter


class DummyAdapter(ExchangeAdapter):
    def __init__(self) -> None:
        self.orders: list[OrderSpec] = []

    def fetch_order_book(self, symbol: str) -> dict:
        return {}

    def create_order(self, order: OrderSpec) -> Fill:
        self.orders.append(order)
        return Fill(
            order_id=str(len(self.orders)),
            symbol=order.symbol,
            side=order.side,
            price=order.price or 0.0,
            quantity=order.quantity,
            fee=0.0,
        )

    def cancel_order(self, order_id: str, symbol: str) -> None:  # pragma: no cover - not used
        pass

    def fetch_balance(self, asset: str) -> float:  # pragma: no cover - not used
        return 0.0


def profitable_books() -> dict[str, dict[str, list[tuple[float, float]]]]:
    return {
        "ETH/USDT": {"asks": [(100.0, 10.0)], "bids": []},
        "BTC/ETH": {"bids": [(0.1, 10.0)], "asks": []},
        "BTC/USDT": {"bids": [(1100.0, 10.0)], "asks": []},
    }


def unprofitable_books() -> dict[str, dict[str, list[tuple[float, float]]]]:
    data = profitable_books()
    data["BTC/USDT"] = {"bids": [(1000.0, 10.0)], "asks": []}
    return data


def test_try_triangle_executes_on_profit() -> None:
    adapter = DummyAdapter()
    tri = Triangle("ETH/USDT", "BTC/ETH", "BTC/USDT")
    placed = try_triangle(adapter, tri, profitable_books(), 0.01)
    assert placed is True
    assert len(adapter.orders) == 3


def test_try_triangle_skips_when_unprofitable() -> None:
    adapter = DummyAdapter()
    tri = Triangle("ETH/USDT", "BTC/ETH", "BTC/USDT")
    placed = try_triangle(adapter, tri, unprofitable_books(), 0.01)
    assert placed is False
    assert len(adapter.orders) == 0
