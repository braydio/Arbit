"""Database helper tests for persistence layer."""

from datetime import datetime

from arbit.models import Fill, Triangle
from arbit.persistence import db


def test_insert_triangle_and_fill() -> None:
    """Records can be inserted and retrieved from the database."""
    conn = db.init_db(":memory:")
    tri = Triangle("ETH/USDT", "ETH/BTC", "BTC/USDT")
    t_id = db.insert_triangle(conn, tri)
    assert t_id == 1

    fill = Fill(
        order_id="o1",
        symbol="BTC/USDT",
        side="buy",
        price=100.0,
        quantity=0.5,
        fee=0.1,
        timestamp=datetime.fromtimestamp(0),
    )
    f_id = db.insert_fill(conn, fill)
    assert f_id == 1

    cur = conn.cursor()
    cur.execute("SELECT leg_ab, leg_bc, leg_ac FROM triangles")
    assert cur.fetchone() == ("ETH/USDT", "ETH/BTC", "BTC/USDT")
    cur.execute("SELECT order_id, symbol, side, price, quantity, fee FROM fills")
    assert cur.fetchone() == ("o1", "BTC/USDT", "buy", 100.0, 0.5, 0.1)
