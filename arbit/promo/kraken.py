"""Safely execute a Kraken trade to satisfy promotional volume requirements."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any, Mapping

import typer

from arbit.adapters.base import OrderSpec
from arbit.adapters.ccxt_adapter import CCXTAdapter
from arbit.config import settings

LOGGER = logging.getLogger(__name__)

STABLE_ASSETS = {
    "USDT",
    "USDC",
    "DAI",
    "BUSD",
    "USDP",
    "TUSD",
    "GUSD",
    "PAX",
    "USD",
    "EUR",
    "GBP",
    "CHF",
    "AUD",
    "CAD",
    "JPY",
}
"""Assets treated as stable for promotion eligibility checks."""

PROMO_MIN_NOTIONAL = Decimal("50")
"""Minimum USD notional required to qualify for the Kraken promotion."""

FUDGE_FACTOR = Decimal("1.002")
"""Increase applied before rounding to remain above the promotional threshold."""

app = typer.Typer(help="Kraken promotion helper that defaults to a safe dry run.")


@dataclass
class TradePlan:
    """Container describing the intended Kraken trade."""

    symbol: str
    base: str
    quote: str
    usd_target: Decimal
    ask_price: Decimal
    bid_price: Decimal
    quantity: Decimal
    notional: Decimal

    def spread_bps(self) -> Decimal:
        """Return the bid/ask spread in basis points."""

        if self.ask_price == 0:
            return Decimal(0)
        return (self.ask_price - self.bid_price) / self.ask_price * Decimal("10000")


@dataclass
class ExecutionResult:
    """Summary of submitted Kraken orders."""

    buy: Mapping[str, Any] | None
    sell: Mapping[str, Any] | None
    dry_run: bool


class PromoError(RuntimeError):
    """Raised when the promo workflow cannot continue safely."""


def is_stable_asset(asset: str) -> bool:
    """Return ``True`` when *asset* is considered stable."""

    return asset.upper() in STABLE_ASSETS


def _to_decimal(value: Any) -> Decimal:
    """Convert *value* to :class:`~decimal.Decimal` preserving precision."""

    if isinstance(value, Decimal):
        return value
    if isinstance(value, (int, float, str)):
        return Decimal(str(value))
    raise TypeError(f"Unsupported numeric value: {value!r}")


def _apply_precision(quantity: Decimal, market: Mapping[str, Any]) -> Decimal:
    """Round *quantity* down to comply with market precision settings."""

    precision = market.get("precision", {}).get("amount")
    if precision is not None:
        try:
            precision = int(precision)
            if precision >= 0:
                step = Decimal(1).scaleb(-precision)
                quantity = quantity.quantize(step, rounding=ROUND_DOWN)
        except Exception as exc:  # pragma: no cover - defensive path
            raise PromoError(f"Invalid amount precision: {precision}") from exc
    return quantity


def _validate_amount_bounds(quantity: Decimal, market: Mapping[str, Any]) -> None:
    """Ensure *quantity* satisfies the market's minimum trade size."""

    min_amount = market.get("limits", {}).get("amount", {}).get("min")
    if min_amount:
        min_amount_dec = _to_decimal(min_amount)
        if quantity < min_amount_dec:
            raise PromoError(
                "Calculated quantity is below Kraken's minimum amount. "
                "Increase the USD amount or choose a different asset."
            )


def plan_trade(
    adapter: CCXTAdapter,
    base: str,
    quote: str,
    usd_amount: Decimal,
    *,
    orderbook_depth: int = 5,
) -> TradePlan:
    """Generate a :class:`TradePlan` for a Kraken promo trade."""

    base = base.upper()
    quote = quote.upper()
    usd_amount = usd_amount.quantize(Decimal("0.01"))

    if usd_amount <= PROMO_MIN_NOTIONAL:
        raise PromoError("USD amount must be greater than $50.00 to qualify.")

    markets = adapter.load_markets()
    symbol = f"{base}/{quote}"
    market = markets.get(symbol)
    if not market:
        raise PromoError(f"Symbol {symbol} is not available on Kraken.")

    if is_stable_asset(market.get("base", base)):
        raise PromoError(
            f"{base} is classified as a stable asset. Choose a non-stable asset."
        )

    min_notional = _to_decimal(adapter.min_notional(symbol))
    if min_notional > usd_amount:
        raise PromoError(
            "Kraken's minimum notional exceeds the requested USD amount. "
            "Increase --usd-amount to proceed."
        )

    orderbook = adapter.fetch_orderbook(symbol, orderbook_depth)
    asks = orderbook.get("asks") or []
    bids = orderbook.get("bids") or []
    if not asks or not bids:
        raise PromoError("Order book depth is insufficient to plan the trade.")

    ask_price = _to_decimal(asks[0][0])
    bid_price = _to_decimal(bids[0][0])
    if ask_price <= 0:
        raise PromoError("Invalid ask price returned by Kraken.")

    raw_qty = usd_amount / ask_price
    padded_qty = raw_qty * FUDGE_FACTOR
    quantity = _apply_precision(padded_qty, market)
    _validate_amount_bounds(quantity, market)

    notional = (quantity * ask_price).quantize(Decimal("0.01"))
    if notional <= PROMO_MIN_NOTIONAL:
        raise PromoError(
            "Rounded trade size falls below the $50 requirement. Increase the "
            "USD amount or try again when spreads are tighter."
        )

    return TradePlan(
        symbol=symbol,
        base=base,
        quote=quote,
        usd_target=usd_amount,
        ask_price=ask_price,
        bid_price=bid_price,
        quantity=quantity,
        notional=notional,
    )


def execute_plan(
    adapter: CCXTAdapter,
    plan: TradePlan,
    *,
    execute: bool,
    sell_back: bool,
) -> ExecutionResult:
    """Submit the promo trade described by *plan* if ``execute`` is true."""

    if not execute:
        return ExecutionResult(buy=None, sell=None, dry_run=True)

    if settings.dry_run:
        raise PromoError(
            "DRY_RUN is enabled. Export DRY_RUN=false to allow live trading."
        )

    buy_spec = OrderSpec(symbol=plan.symbol, side="buy", qty=float(plan.quantity))
    LOGGER.info(
        "Submitting Kraken buy order symbol=%s qty=%s", plan.symbol, plan.quantity
    )
    buy_fill = adapter.create_order(buy_spec)

    sell_fill: Mapping[str, Any] | None = None
    if sell_back:
        sell_qty = _to_decimal(buy_fill.get("qty", plan.quantity))
        if sell_qty > 0:
            sell_spec = OrderSpec(symbol=plan.symbol, side="sell", qty=float(sell_qty))
            LOGGER.info(
                "Submitting Kraken sell order symbol=%s qty=%s", plan.symbol, sell_qty
            )
            sell_fill = adapter.create_order(sell_spec)
        else:
            LOGGER.warning("Buy fill returned zero quantity; skipping sell leg.")

    return ExecutionResult(buy=buy_fill, sell=sell_fill, dry_run=False)


def _format_plan(plan: TradePlan) -> str:
    """Return a human-readable summary for *plan*."""

    return (
        f"Kraken promo plan → buy {plan.quantity} {plan.base} at ~{plan.ask_price} {plan.quote} "
        f"(notional ≈ ${plan.notional}). Spread ≈ {plan.spread_bps():.2f} bps."
    )


@app.command("trade")
def promo_trade(
    base: str = typer.Option("ETH", help="Non-stable asset to purchase."),
    quote: str = typer.Option("USD", help="Quote currency to spend."),
    usd_amount: float = typer.Option(
        55.0, help="USD amount to spend. Must exceed $50 to qualify."
    ),
    depth: int = typer.Option(5, help="Order book depth used for planning."),
    sell_back: bool = typer.Option(
        True, "--sell-back/--hold", help="Sell the asset back to the quote currency."
    ),
    execute: bool = typer.Option(
        False, "--execute", help="Submit live orders when DRY_RUN=false."
    ),
    log_level: str = typer.Option("INFO", help="Logging level for script output."),
) -> None:
    """Plan and optionally execute a Kraken trade for the BTC promo."""

    logging.basicConfig(
        level=getattr(logging, log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    adapter = CCXTAdapter("kraken")
    try:
        plan = plan_trade(adapter, base, quote, _to_decimal(usd_amount), orderbook_depth=depth)
        typer.echo(_format_plan(plan))

        result = execute_plan(adapter, plan, execute=execute, sell_back=sell_back)
        if result.dry_run:
            typer.echo("Dry run complete. Re-run with --execute and DRY_RUN=false to trade.")
        else:
            typer.echo(
                f"Buy order id={result.buy.get('id')} qty={result.buy.get('qty')} price={result.buy.get('price')}"
            )
            if result.sell:
                typer.echo(
                    f"Sell order id={result.sell.get('id')} qty={result.sell.get('qty')} price={result.sell.get('price')}"
                )
            else:
                typer.echo("Sell leg skipped; asset retained.")
    except PromoError as exc:
        LOGGER.error("Promo trade failed: %s", exc)
        raise typer.Exit(code=1) from exc
    finally:
        try:
            asyncio.run(adapter.close())
        except RuntimeError:
            LOGGER.debug("Event loop already running; closing adapter synchronously.")
            try:
                if hasattr(adapter, "ex") and hasattr(adapter.ex, "close"):
                    adapter.ex.close()
            except Exception:
                LOGGER.debug("Failed to close ccxt client cleanly.")


if __name__ == "__main__":  # pragma: no cover - manual invocation helper
    app()
