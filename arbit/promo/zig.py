"""Kraken ZIG promotion workflow helpers."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Awaitable, Callable, Mapping, Tuple

from arbit.adapters.ccxt_adapter import CCXTAdapter
from arbit.config import settings
from arbit.models import OrderSpec

from .kraken import (
    FUDGE_FACTOR,
    PromoError,
    _apply_precision,
    _to_decimal,
    _validate_amount_bounds,
)

TARGET_ZIG_BALANCE = Decimal("2500")
"""Default number of ZIG tokens required for the promotion."""

SELL_TIME_UTC = datetime(2024, 10, 6, 0, 1, tzinfo=timezone.utc)
"""Scheduled liquidation timestamp for the promotion (UTC)."""

DEFAULT_BASE_ASSET = "ZIG"
DEFAULT_QUOTE_ASSET = "USD"
DEFAULT_ORDERBOOK_DEPTH = 5

LoggerType = logging.Logger | logging.LoggerAdapter | None


@dataclass(frozen=True)
class BalancePlan:
    """Plan for acquiring additional ZIG to satisfy the promotion target."""

    symbol: str
    base: str
    quote: str
    target_balance: Decimal
    current_balance: Decimal
    quantity: Decimal
    ask_price: Decimal
    notional: Decimal

    def needs_purchase(self) -> bool:
        """Return ``True`` when additional ZIG must be purchased."""

        return self.quantity > 0

    def expected_post_balance(self) -> Decimal:
        """Return the expected ZIG balance after executing the plan."""

        return self.current_balance + self.quantity


@dataclass(frozen=True)
class SellPlan:
    """Plan for liquidating accumulated ZIG at the scheduled time."""

    symbol: str
    base: str
    quote: str
    quantity: Decimal
    bid_price: Decimal
    notional: Decimal


def _market_for(adapter: CCXTAdapter, symbol: str) -> Mapping[str, Any]:
    """Return market metadata for *symbol* or raise :class:`PromoError`."""

    markets = adapter.load_markets()
    market = markets.get(symbol)
    if not market:
        raise PromoError(f"Symbol {symbol} is not available on Kraken.")
    return market


def plan_accumulation(
    adapter: CCXTAdapter,
    target_balance: Decimal,
    *,
    base: str = DEFAULT_BASE_ASSET,
    quote: str = DEFAULT_QUOTE_ASSET,
    orderbook_depth: int = DEFAULT_ORDERBOOK_DEPTH,
) -> BalancePlan:
    """Return a :class:`BalancePlan` describing required ZIG purchases."""

    base = base.upper()
    quote = quote.upper()
    symbol = f"{base}/{quote}"

    market = _market_for(adapter, symbol)

    current_balance = _to_decimal(adapter.fetch_balance(base))
    target_balance = _to_decimal(target_balance)

    deficit = target_balance - current_balance
    if deficit <= 0:
        return BalancePlan(
            symbol=symbol,
            base=base,
            quote=quote,
            target_balance=target_balance,
            current_balance=current_balance,
            quantity=Decimal("0"),
            ask_price=Decimal("0"),
            notional=Decimal("0"),
        )

    orderbook = adapter.fetch_orderbook(symbol, orderbook_depth)
    asks = orderbook.get("asks") or []
    if not asks:
        raise PromoError("Order book depth is insufficient to accumulate ZIG.")

    ask_price = _to_decimal(asks[0][0])
    if ask_price <= 0:
        raise PromoError("Invalid ask price returned by Kraken.")

    padded_qty = deficit * FUDGE_FACTOR
    quantity = _apply_precision(padded_qty, market)
    _validate_amount_bounds(quantity, market)

    if quantity <= 0:
        raise PromoError(
            "Rounded ZIG quantity is zero; increase the target balance or "
            "check market precision settings."
        )

    expected_post = current_balance + quantity
    if expected_post < target_balance:
        shortfall = target_balance - expected_post
        incremental = _apply_precision(shortfall * FUDGE_FACTOR, market)
        if incremental <= 0:
            raise PromoError(
                "Unable to reach the target balance after applying precision "
                "constraints. Increase the target or review market precision."
            )
        quantity += incremental

    notional = (quantity * ask_price).quantize(Decimal("0.01"))

    return BalancePlan(
        symbol=symbol,
        base=base,
        quote=quote,
        target_balance=target_balance,
        current_balance=current_balance,
        quantity=quantity,
        ask_price=ask_price,
        notional=notional,
    )


def execute_accumulation(
    adapter: CCXTAdapter,
    plan: BalancePlan,
    *,
    execute: bool,
) -> Mapping[str, Any] | None:
    """Execute *plan* and return the resulting order when ``execute`` is true."""

    if not plan.needs_purchase() or not execute:
        return None

    if settings.dry_run:
        raise PromoError("DRY_RUN is enabled. Export DRY_RUN=false to trade.")

    order = OrderSpec(
        symbol=plan.symbol,
        side="buy",
        quantity=float(plan.quantity),
        price=None,
        order_type="market",
    )
    return adapter.create_order(order)


def plan_liquidation(
    adapter: CCXTAdapter,
    *,
    base: str = DEFAULT_BASE_ASSET,
    quote: str = DEFAULT_QUOTE_ASSET,
    orderbook_depth: int = DEFAULT_ORDERBOOK_DEPTH,
) -> SellPlan | None:
    """Return a :class:`SellPlan` describing how to liquidate ZIG holdings."""

    base = base.upper()
    quote = quote.upper()
    symbol = f"{base}/{quote}"

    market = _market_for(adapter, symbol)

    balance = _to_decimal(adapter.fetch_balance(base))
    if balance <= 0:
        return None

    orderbook = adapter.fetch_orderbook(symbol, orderbook_depth)
    bids = orderbook.get("bids") or []
    if not bids:
        raise PromoError("Order book depth is insufficient to liquidate ZIG.")

    bid_price = _to_decimal(bids[0][0])
    if bid_price <= 0:
        raise PromoError("Invalid bid price returned by Kraken.")

    quantity = _apply_precision(balance, market)
    _validate_amount_bounds(quantity, market)

    if quantity <= 0:
        raise PromoError(
            "Rounded ZIG quantity is zero; check balance precision before selling."
        )

    notional = (quantity * bid_price).quantize(Decimal("0.01"))

    return SellPlan(
        symbol=symbol,
        base=base,
        quote=quote,
        quantity=quantity,
        bid_price=bid_price,
        notional=notional,
    )


def execute_liquidation(
    adapter: CCXTAdapter,
    plan: SellPlan | None,
    *,
    execute: bool,
) -> Mapping[str, Any] | None:
    """Execute *plan* and return the resulting sell order when ``execute`` is true."""

    if plan is None or not execute:
        return None

    if settings.dry_run:
        raise PromoError("DRY_RUN is enabled. Export DRY_RUN=false to trade.")

    order = OrderSpec(
        symbol=plan.symbol,
        side="sell",
        quantity=float(plan.quantity),
        price=None,
        order_type="market",
    )
    return adapter.create_order(order)


def _utcnow() -> datetime:
    """Return the current UTC datetime."""

    return datetime.now(timezone.utc)


async def wait_until(
    target: datetime,
    *,
    now: Callable[[], datetime] | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
    check_interval: int = 300,
) -> None:
    """Suspend execution until *target* UTC time is reached."""

    now_fn = now or _utcnow
    sleep_fn = sleep or asyncio.sleep

    if check_interval <= 0:
        raise ValueError("check_interval must be positive")

    target = target.astimezone(timezone.utc)

    while True:
        remaining = (target - now_fn()).total_seconds()
        if remaining <= 0:
            return
        await sleep_fn(min(remaining, float(check_interval)))


async def run_promo_workflow(
    adapter: CCXTAdapter,
    *,
    target_balance: Decimal = TARGET_ZIG_BALANCE,
    sell_at: datetime = SELL_TIME_UTC,
    execute: bool = False,
    base: str = DEFAULT_BASE_ASSET,
    quote: str = DEFAULT_QUOTE_ASSET,
    orderbook_depth: int = DEFAULT_ORDERBOOK_DEPTH,
    logger: LoggerType = None,
    now: Callable[[], datetime] | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
    check_interval: int = 300,
) -> Tuple[
    BalancePlan,
    Mapping[str, Any] | None,
    SellPlan | None,
    Mapping[str, Any] | None,
]:
    """Run the end-to-end ZIG promotion workflow on Kraken."""

    plan = plan_accumulation(
        adapter,
        target_balance,
        base=base,
        quote=quote,
        orderbook_depth=orderbook_depth,
    )
    if logger:
        logger.info(
            "Promo plan: current=%s target=%s quantity=%s notional≈$%s",
            plan.current_balance,
            plan.target_balance,
            plan.quantity,
            plan.notional,
        )

    buy_fill = execute_accumulation(adapter, plan, execute=execute)
    if logger and buy_fill:
        logger.info(
            "Submitted buy order id=%s qty=%s price=%s",
            buy_fill.get("id"),
            buy_fill.get("qty"),
            buy_fill.get("price"),
        )

    if not execute:
        if logger:
            logger.info(
                "Dry run complete. Re-run with --execute and DRY_RUN=false to trade."
            )
        return plan, None, None, None

    await wait_until(
        sell_at,
        now=now,
        sleep=sleep,
        check_interval=check_interval,
    )

    sell_plan = plan_liquidation(
        adapter,
        base=base,
        quote=quote,
        orderbook_depth=orderbook_depth,
    )
    if sell_plan is None:
        if logger:
            logger.warning(
                "No ZIG balance detected at liquidation time; skipping sell."
            )
        return plan, buy_fill, None, None

    if logger:
        logger.info(
            "Liquidation plan: quantity=%s notional≈$%s",
            sell_plan.quantity,
            sell_plan.notional,
        )

    sell_fill = execute_liquidation(adapter, sell_plan, execute=execute)
    if logger and sell_fill:
        logger.info(
            "Submitted sell order id=%s qty=%s price=%s",
            sell_fill.get("id"),
            sell_fill.get("qty"),
            sell_fill.get("price"),
        )

    return plan, buy_fill, sell_plan, sell_fill


__all__ = [
    "BalancePlan",
    "SellPlan",
    "TARGET_ZIG_BALANCE",
    "SELL_TIME_UTC",
    "DEFAULT_BASE_ASSET",
    "DEFAULT_QUOTE_ASSET",
    "DEFAULT_ORDERBOOK_DEPTH",
    "plan_accumulation",
    "execute_accumulation",
    "plan_liquidation",
    "execute_liquidation",
    "wait_until",
    "run_promo_workflow",
]
