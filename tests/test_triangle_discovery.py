from arbit.engine.triangle import discover_triangles_from_markets


def test_discover_triangles_basic():
    ms = {
        "ETH/USDT": {"base": "ETH", "quote": "USDT"},
        "ETH/BTC": {"base": "ETH", "quote": "BTC"},
        "BTC/USDT": {"base": "BTC", "quote": "USDT"},
    }
    assert discover_triangles_from_markets(ms) == [["ETH/USDT", "ETH/BTC", "BTC/USDT"]]


def test_discover_triangles_multiple_and_parse_symbol():
    ms = {
        "ETH/USDT": {},
        "ETH/BTC": {},
        "BTC/USDT": {},
        "ETH/USDC": {},
        "BTC/USDC": {},
    }
    tris = discover_triangles_from_markets(ms)
    assert ["ETH/USDT", "ETH/BTC", "BTC/USDT"] in tris
    assert ["ETH/USDC", "ETH/BTC", "BTC/USDC"] in tris
    assert len(tris) == 2
