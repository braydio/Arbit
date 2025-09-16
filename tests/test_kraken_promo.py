"""Tests for the Kraken promotional trading helper."""

from decimal import Decimal

import pytest

from arbit.promo.kraken import (
    ExecutionResult,
    PromoError,
    TradePlan,
    execute_plan,
    is_stable_asset,
    plan_trade,
)


class DummyAdapter:
    """Minimal adapter stub for exercising promo logic."""

    def __init__(self) -> None:
        self._markets = {
            "ETH/USD": {
                "base": "ETH",
                "quote": "USD",
                "precision": {"amount": 5},
                "limits": {"amount": {"min": 0.0001}},
            }
        }
        self._orderbook = {
            "asks": [[2000.0, 1.0]],
            "bids": [[1999.5, 1.0]],
        }
        self._min_notional = 5.0
        self.orders = []

    def load_markets(self):
        return self._markets

    def min_notional(self, symbol):
        return self._min_notional

    def fetch_orderbook(self, symbol, depth):
        return self._orderbook

    def create_order(self, spec):
        self.orders.append(spec)
        side_price = 2000.0 if spec.side == "buy" else 1999.5
        return {
            "id": f"{spec.side}-{len(self.orders)}",
            "symbol": spec.symbol,
            "side": spec.side,
            "price": side_price,
            "qty": spec.qty,
            "fee": 0.0,
        }


def test_is_stable_asset_detection():
    """Stable asset detection should be case insensitive."""

    assert is_stable_asset("usdt")
    assert not is_stable_asset("eth")


def test_plan_trade_generates_valid_plan(monkeypatch):
    """Planning a trade should return a notional comfortably above $50."""

    adapter = DummyAdapter()
    plan = plan_trade(adapter, "eth", "usd", Decimal("55"))
    assert isinstance(plan, TradePlan)
    assert plan.base == "ETH"
    assert plan.quote == "USD"
    assert plan.notional > Decimal("50")
    assert plan.quantity > 0


def test_plan_trade_rejects_stable_asset(monkeypatch):
    """Stable coins must not be considered eligible base assets."""

    adapter = DummyAdapter()
    adapter._markets["USDC/USD"] = {
        "base": "USDC",
        "quote": "USD",
        "precision": {"amount": 5},
        "limits": {"amount": {"min": 0.0001}},
    }
    with pytest.raises(PromoError):
        plan_trade(adapter, "usdc", "usd", Decimal("55"))


def test_plan_trade_requires_over_fifty_dollars():
    """Amounts at or below $50 should be rejected."""

    adapter = DummyAdapter()
    with pytest.raises(PromoError):
        plan_trade(adapter, "eth", "usd", Decimal("50"))


def test_execute_plan_respects_dry_run(monkeypatch):
    """Live execution should be blocked while dry run mode is enabled."""

    from arbit.config import settings

    adapter = DummyAdapter()
    plan = plan_trade(adapter, "eth", "usd", Decimal("55"))
    monkeypatch.setattr(settings, "dry_run", True)
    with pytest.raises(PromoError):
        execute_plan(adapter, plan, execute=True, sell_back=True)


def test_execute_plan_places_orders_when_live(monkeypatch):
    """When dry run is disabled the helper should submit buy and sell orders."""

    from arbit.config import settings

    adapter = DummyAdapter()
    plan = plan_trade(adapter, "eth", "usd", Decimal("55"))
    monkeypatch.setattr(settings, "dry_run", False)
    result = execute_plan(adapter, plan, execute=True, sell_back=True)
    assert isinstance(result, ExecutionResult)
    assert not result.dry_run
    assert len(adapter.orders) == 2
    assert result.buy["side"] == "buy"
    assert result.sell["side"] == "sell"
