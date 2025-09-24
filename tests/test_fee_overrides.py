"""Tests for configurable fee overrides."""

from types import SimpleNamespace

import pytest

from arbit.adapters.ccxt_adapter import CCXTAdapter


def test_kraken_fees_use_market_rates():
    """Kraken fees should come directly from ccxt market metadata."""

    adapter = object.__new__(CCXTAdapter)
    adapter._fee = {}

    def market(_symbol: str):
        return {"maker": 0.0015, "taker": 0.0026}

    adapter.ex = SimpleNamespace(
        id="kraken",
        fees={"trading": {"maker": 0.0015, "taker": 0.0026}},
        market=market,
    )

    maker, taker = CCXTAdapter.fetch_fees(adapter, "ETH/USDT")

    assert maker == pytest.approx(0.0015)
    assert taker == pytest.approx(0.0026)

    # Cached path should still return the same market-derived fees.
    maker_cached, taker_cached = CCXTAdapter.fetch_fees(adapter, "ETH/USDT")
    assert maker_cached == pytest.approx(0.0015)
    assert taker_cached == pytest.approx(0.0026)
