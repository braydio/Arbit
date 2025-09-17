"""Tests for configurable fee overrides."""

from types import SimpleNamespace

from arbit.adapters.ccxt_adapter import CCXTAdapter
from arbit.config import settings


def test_kraken_fee_override(monkeypatch):
    """Custom BPS overrides should replace ccxt-derived maker/taker fees."""

    adapter = object.__new__(CCXTAdapter)
    adapter._fee = {}

    def market(_symbol: str):
        return {"maker": 0.0015, "taker": 0.0026}

    adapter.ex = SimpleNamespace(
        id="kraken",
        fees={"trading": {"maker": 0.0015, "taker": 0.0026}},
        market=market,
    )

    monkeypatch.setattr(settings, "kraken_maker_fee_bps", 0.0)
    monkeypatch.setattr(settings, "kraken_taker_fee_bps", 0.0)

    maker, taker = CCXTAdapter.fetch_fees(adapter, "ETH/USDT")

    assert maker == 0.0
    assert taker == 0.0

    # Cached path should still honor overrides
    maker_cached, taker_cached = CCXTAdapter.fetch_fees(adapter, "ETH/USDT")
    assert maker_cached == 0.0
    assert taker_cached == 0.0
