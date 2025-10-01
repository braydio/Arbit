"""Tests for the Kraken ZIG promotion workflow."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest

from arbit.promo.kraken import PromoError
from arbit.promo.zig import (
    TARGET_ZIG_BALANCE,
    execute_accumulation,
    plan_accumulation,
    plan_liquidation,
    run_promo_workflow,
    wait_until,
)


class DummyAdapter:
    """Minimal adapter implementation for exercising promo logic."""

    def __init__(self, balance: Decimal) -> None:
        self.base_asset = "ZIG"
        self.quote_asset = "USD"
        self._balance = Decimal(balance)
        self.ask_price = Decimal("0.12")
        self.bid_price = Decimal("0.119")
        self.orders: list[dict[str, Any]] = []
        self._markets = {
            "ZIG/USD": {
                "base": "ZIG",
                "quote": "USD",
                "precision": {"amount": 3},
                "limits": {"amount": {"min": 0.1}},
            }
        }

    def load_markets(self) -> dict[str, Any]:
        return self._markets

    def fetch_balance(self, asset: str) -> float:
        if asset.upper() == self.base_asset:
            return float(self._balance)
        return 0.0

    def fetch_orderbook(self, symbol: str, depth: int) -> dict[str, Any]:
        return {
            "asks": [[float(self.ask_price), 10_000.0]],
            "bids": [[float(self.bid_price), 10_000.0]],
        }

    def create_order(self, spec: Any) -> dict[str, Any]:
        qty = Decimal(str(getattr(spec, "quantity", getattr(spec, "qty"))))
        side = getattr(spec, "side")
        price = float(self.ask_price if side == "buy" else self.bid_price)
        if side == "buy":
            self._balance += qty
        else:
            self._balance -= qty
        order = {
            "id": f"{side}-{len(self.orders) + 1}",
            "symbol": spec.symbol,
            "side": side,
            "qty": float(qty),
            "price": price,
        }
        self.orders.append(order)
        return order

    async def close(self) -> None:  # pragma: no cover - provided for interface parity
        return None


def test_plan_accumulation_requires_purchase() -> None:
    """Planning should request a buy when the balance is below target."""

    adapter = DummyAdapter(Decimal("1000"))
    plan = plan_accumulation(adapter, TARGET_ZIG_BALANCE)
    assert plan.needs_purchase()
    assert plan.quantity > 0
    assert plan.expected_post_balance() >= TARGET_ZIG_BALANCE


def test_plan_accumulation_skips_when_balance_sufficient() -> None:
    """No purchase should be required when the account already meets the target."""

    adapter = DummyAdapter(Decimal("2600"))
    plan = plan_accumulation(adapter, TARGET_ZIG_BALANCE)
    assert not plan.needs_purchase()
    assert plan.quantity == 0


def test_execute_accumulation_respects_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """Execution must raise when DRY_RUN is active."""

    from arbit.config import settings

    adapter = DummyAdapter(Decimal("2000"))
    plan = plan_accumulation(adapter, TARGET_ZIG_BALANCE)
    monkeypatch.setattr(settings, "dry_run", True)
    with pytest.raises(PromoError):
        execute_accumulation(adapter, plan, execute=True)


def test_plan_liquidation_handles_empty_balance() -> None:
    """When no ZIG is held, liquidation planning should return ``None``."""

    adapter = DummyAdapter(Decimal("0"))
    assert plan_liquidation(adapter) is None


@pytest.mark.asyncio
async def test_wait_until_advances_time() -> None:
    """wait_until should sleep until the scheduled timestamp."""

    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    target = start + timedelta(seconds=120)
    calls: list[float] = []

    class Controller:
        def __init__(self) -> None:
            self.current = start

        def now(self) -> datetime:
            return self.current

        async def sleep(self, seconds: float) -> None:
            calls.append(seconds)
            self.current += timedelta(seconds=seconds)

    controller = Controller()
    await wait_until(
        target, now=controller.now, sleep=controller.sleep, check_interval=30
    )
    assert controller.current >= target
    assert calls  # ensure sleep was invoked


@pytest.mark.asyncio
async def test_run_promo_workflow_places_buy_and_sell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end workflow should buy then sell when execution is enabled."""

    from arbit.config import settings

    adapter = DummyAdapter(Decimal("1500"))
    monkeypatch.setattr(settings, "dry_run", False)

    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    controller_times: list[float] = []

    class Controller:
        def __init__(self) -> None:
            self.current = start

        def now(self) -> datetime:
            return self.current

        async def sleep(self, seconds: float) -> None:
            controller_times.append(seconds)
            self.current += timedelta(seconds=seconds)

    controller = Controller()
    sell_at = start + timedelta(seconds=90)

    plan, buy_fill, sell_plan, sell_fill = await run_promo_workflow(
        adapter,
        target_balance=TARGET_ZIG_BALANCE,
        sell_at=sell_at,
        execute=True,
        now=controller.now,
        sleep=controller.sleep,
        check_interval=30,
    )

    assert plan.needs_purchase()
    assert buy_fill is not None
    assert sell_plan is not None
    assert sell_fill is not None
    assert controller_times  # ensures wait_until slept at least once
    assert adapter.orders[0]["side"] == "buy"
    assert adapter.orders[-1]["side"] == "sell"
