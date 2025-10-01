"""CLI command for executing the Kraken ZIG promotion workflow."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import typer

from ..core import TyperOption, app, log
from ..utils import CCXTAdapter

# Defaults mirror the promotion helper in :mod:`arbit.promo.zig`.
DEFAULT_TARGET_ZIG = 2500.0
DEFAULT_QUOTE_ASSET = "USD"
DEFAULT_SELL_AT = "2024-10-06T00:01:00+00:00"


def _parse_datetime(value: str) -> datetime:
    """Return ``datetime`` parsed from ISO-8601 string *value*."""

    if not value:
        raise ValueError("Timestamp cannot be empty")

    try:
        dt = datetime.fromisoformat(value)
    except ValueError as exc:
        if value.endswith("Z"):
            dt = datetime.fromisoformat(value[:-1] + "+00:00")
        else:
            raise ValueError(str(exc)) from exc

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt


@app.command("promo")
def promo(
    execute: bool = TyperOption(
        False, "--execute", help="Place live orders when DRY_RUN=false."
    ),
    target: float = TyperOption(
        DEFAULT_TARGET_ZIG,
        "--target",
        help="Target ZIG balance to hold before scheduling the sell order.",
    ),
    quote: str = TyperOption(
        DEFAULT_QUOTE_ASSET,
        "--quote",
        help="Quote currency for ZIG trades (default: USD).",
    ),
    sell_at: str = TyperOption(
        DEFAULT_SELL_AT,
        "--sell-at",
        help="UTC timestamp for liquidation (ISO 8601).",
    ),
    check_interval: int = TyperOption(
        300,
        "--check-interval",
        help="Seconds between wake-ups while waiting to sell.",
    ),
) -> None:
    """Buy ZIG up to the target amount and schedule an automatic liquidation."""

    try:
        target_balance = Decimal(str(target))
    except InvalidOperation as exc:
        log.error("promo: invalid --target value: %s", exc)
        raise typer.Exit(code=1) from exc

    try:
        sell_at_dt = _parse_datetime(sell_at)
    except ValueError as exc:
        log.error("promo: invalid --sell-at timestamp '%s': %s", sell_at, exc)
        raise typer.Exit(code=1) from exc

    if check_interval <= 0:
        log.error("promo: --check-interval must be positive")
        raise typer.Exit(code=1)

    quote = quote.upper()

    adapter = CCXTAdapter("kraken")

    # Import lazily so test suites can stub arbit.config before module import.
    from arbit.promo.kraken import PromoError
    from arbit.promo.zig import run_promo_workflow

    async def _runner() -> None:
        try:
            await run_promo_workflow(
                adapter,
                target_balance=target_balance,
                sell_at=sell_at_dt,
                execute=execute,
                quote=quote,
                logger=log,
                check_interval=check_interval,
            )
        finally:
            try:
                await adapter.close()
            except RuntimeError:
                if hasattr(adapter, "ex") and hasattr(adapter.ex, "close"):
                    adapter.ex.close()

    try:
        asyncio.run(_runner())
    except PromoError as exc:
        log.error("promo failed: %s", exc)
        raise typer.Exit(code=1) from exc


__all__ = ["promo"]
