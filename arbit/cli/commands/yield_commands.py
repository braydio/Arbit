"""Yield management CLI commands."""

from __future__ import annotations

import json
import os
import time
import urllib.request
from datetime import datetime, timezone

from arbit.config import settings
from arbit.metrics.exporter import (
    YIELD_ALERTS_TOTAL,
    YIELD_APR,
    YIELD_BEST_APR,
    YIELD_CHECKS_TOTAL,
    YIELD_DEPOSITS_TOTAL,
    YIELD_ERRORS_TOTAL,
    YIELD_WITHDRAWS_TOTAL,
    start_metrics_server,
)
from arbit.notify import fmt_usd, notify_discord
from arbit.persistence.db import init_db, insert_yield_op

from ..core import app, log
from ..utils import AaveProvider


def _raw_to_usd(raw: int | None) -> float | None:
    """Return USD-denominated float for six-decimal stablecoin *raw* units.

    Parameters
    ----------
    raw:
        Balance expressed in raw integer units (e.g., 6-decimal USDC) or
        ``None`` when unavailable.

    Returns
    -------
    float | None
        Balance converted to USD and rounded to six decimal places, or
        ``None`` when the input is ``None``.
    """

    if raw is None:
        return None
    return round(int(raw) / 1_000_000.0, 6)


def _round_optional(value: float | None) -> float | None:
    """Return *value* rounded to six decimals when not ``None``."""

    if value is None:
        return None
    return round(float(value), 6)


def _yield_status(
    *,
    action: str,
    asset: str,
    mode: str,
    stage: str,
    wallet_raw_before: int,
    wallet_raw_after: int | None = None,
    deposit_raw_before: int | None = None,
    deposit_raw_after: int | None = None,
    action_amount_raw: int | None = None,
    reserve_target_usd: float | None = None,
    reserve_abs_usd: float | None = None,
    reserve_percent: float | None = None,
    available_usd: float | None = None,
    wallet_deficit_usd: float | None = None,
    min_stake_raw: int | None = None,
    result: str | None = None,
    reason: str | None = None,
    error: str | None = None,
) -> dict[str, object]:
    """Return structured status context for yield commands.

    Parameters
    ----------
    action:
        Either ``"deposit"`` or ``"withdraw"`` describing the command.
    asset:
        Asset ticker associated with the command (e.g., ``"USDC"``).
    mode:
        Execution mode string such as ``"dry_run"`` or ``"live"``.
    stage:
        High-level phase identifier (``"plan"``, ``"completed"``,
        ``"skipped"``).
    wallet_raw_before:
        Wallet balance prior to any mutation in raw integer units.
    wallet_raw_after:
        Wallet balance after the action completes when available.
    deposit_raw_before:
        Interest-bearing token balance before the action.
    deposit_raw_after:
        Interest-bearing token balance after the action when available.
    action_amount_raw:
        Raw integer amount requested for the action.
    reserve_target_usd:
        Reserve target in USD.
    reserve_abs_usd:
        Absolute reserve component in USD, if configured.
    reserve_percent:
        Reserve percentage component expressed as a percentage.
    available_usd:
        Amount of capital available for action (positive for deposits).
    wallet_deficit_usd:
        Deficit required to reach the configured reserve for withdrawals.
    min_stake_raw:
        Minimum stake requirement in raw integer units, when relevant.
    result:
        Outcome indicator such as ``"success"``, ``"simulated"``, or
        ``"error"``.
    reason:
        Optional textual reason for skipped actions or validation failures.
    error:
        Optional error string when an exception is raised.

    Returns
    -------
    dict[str, object]
        JSON-serialisable mapping capturing the supplied context.
    """

    status: dict[str, object] = {
        "action": action,
        "asset": asset,
        "mode": mode,
        "stage": stage,
        "wallet_usd_before": _raw_to_usd(wallet_raw_before),
    }
    if result is not None:
        status["result"] = result
    if reason is not None:
        status["reason"] = reason
    if error is not None:
        status["error"] = error
    if wallet_raw_after is not None:
        status["wallet_usd_after"] = _raw_to_usd(wallet_raw_after)
    if deposit_raw_before is not None:
        status["deposit_usd_before"] = _raw_to_usd(deposit_raw_before)
    if deposit_raw_after is not None:
        status["deposit_usd_after"] = _raw_to_usd(deposit_raw_after)
    if action_amount_raw is not None:
        status["action_amount_usd"] = _raw_to_usd(action_amount_raw)
    if min_stake_raw is not None:
        status["min_stake_usd"] = _raw_to_usd(min_stake_raw)
    if available_usd is not None:
        status["available_usd"] = _round_optional(available_usd)
    if wallet_deficit_usd is not None:
        status["wallet_deficit_usd"] = _round_optional(wallet_deficit_usd)
    if (
        reserve_target_usd is not None
        or reserve_abs_usd is not None
        or reserve_percent is not None
    ):
        if reserve_target_usd is not None:
            status["reserve_target_usd"] = _round_optional(reserve_target_usd)
        breakdown: dict[str, float] = {}
        if reserve_abs_usd is not None:
            breakdown["absolute_usd"] = float(_round_optional(reserve_abs_usd))
        if reserve_percent is not None:
            breakdown["percent"] = float(_round_optional(reserve_percent))
        if breakdown:
            status["reserve_breakdown"] = breakdown
    return status


def _emit_status(event: str, context: dict[str, object]) -> None:
    """Emit *context* as a structured log entry for *event*.

    Parameters
    ----------
    event:
        Label describing the status event (e.g., ``"yield:collect"``).
    context:
        Mapping of contextual fields captured via :func:`_yield_status`.
    """

    try:
        payload = json.dumps(context, sort_keys=True, separators=(",", ":"))
    except Exception:
        payload = str(context)
    log.info("%s | %s", event, payload)


def _fmt_usd_optional(amount: float | None) -> str:
    """Return :func:`fmt_usd` formatting for optional *amount* values."""

    if amount is None:
        return "-"
    return fmt_usd(float(amount))


@app.command("yield:collect")
@app.command("yield_collect")
def yield_collect(
    asset: str = "USDC",
    min_stake: int | None = None,
    reserve_usd: float | None = None,
    help_verbose: bool = False,
) -> None:
    """Deposit idle stablecoin into Aave v3 (beta, USDC only).

    The command emits structured status updates describing reserve
    configuration, available capital, and post-action balances to both the
    application log and configured notification channels.
    """

    if help_verbose:
        app.print_verbose_help_for("yield:collect")
        raise SystemExit(0)

    asset_clean = (asset or "").strip().upper()
    if asset_clean != "USDC":
        log.error("yield:collect supports USDC only for now")
        return

    try:
        start_metrics_server(settings.prom_port)
    except Exception:
        pass

    provider = AaveProvider(settings)
    try:
        conn = init_db(settings.sqlite_path)
    except Exception:
        conn = None
    bal_raw = int(provider.get_wallet_balance_raw())
    atoken_before = int(provider.get_deposit_balance_raw())
    bal_usd = bal_raw / 1_000_000.0

    reserve_abs = (
        float(reserve_usd)
        if reserve_usd is not None
        else float(getattr(settings, "reserve_amount_usd", 0.0))
    )
    reserve_pct_cfg = getattr(settings, "reserve_percent", 0.0)
    try:
        reserve_pct_value = float(reserve_pct_cfg)
    except Exception:
        reserve_pct_value = 0.0
    reserve_pct = reserve_pct_value / 100.0
    reserve_pct_amt = bal_usd * reserve_pct if reserve_pct > 0 else 0.0
    reserve_final = max(reserve_abs, reserve_pct_amt)

    available_usd = max(bal_usd - reserve_final, 0.0)
    amount_raw = int(available_usd * 1_000_000)
    min_units = (
        int(min_stake)
        if min_stake is not None
        else int(getattr(settings, "min_usdc_stake", 1_000_000))
    )

    mode = "dry_run" if bool(getattr(settings, "dry_run", True)) else "live"
    plan_context = _yield_status(
        action="deposit",
        asset=asset_clean,
        mode=mode,
        stage="plan",
        wallet_raw_before=bal_raw,
        deposit_raw_before=atoken_before,
        action_amount_raw=amount_raw,
        reserve_target_usd=reserve_final,
        reserve_abs_usd=reserve_abs,
        reserve_percent=reserve_pct_value,
        available_usd=available_usd,
        min_stake_raw=min_units,
    )
    _emit_status("yield:collect", plan_context)

    if amount_raw < min_units:
        skip_context = _yield_status(
            action="deposit",
            asset=asset_clean,
            mode=mode,
            stage="skipped",
            wallet_raw_before=bal_raw,
            deposit_raw_before=atoken_before,
            action_amount_raw=amount_raw,
            reserve_target_usd=reserve_final,
            reserve_abs_usd=reserve_abs,
            reserve_percent=reserve_pct_value,
            available_usd=available_usd,
            min_stake_raw=min_units,
            result="below_minimum",
            reason="available_below_min_stake",
        )
        _emit_status("yield:collect", skip_context)
        log.info(
            "yield:collect skip | available=%s < min_stake=%s (reserve_target=%s, wallet=%s)",
            _fmt_usd_optional(skip_context.get("available_usd")),
            _fmt_usd_optional(skip_context.get("min_stake_usd")),
            _fmt_usd_optional(skip_context.get("reserve_target_usd")),
            _fmt_usd_optional(plan_context.get("wallet_usd_before")),
        )
        return

    if mode == "dry_run":
        wallet_after_raw = bal_raw
        atoken_after_raw = atoken_before
        status = _yield_status(
            action="deposit",
            asset=asset_clean,
            mode=mode,
            stage="completed",
            wallet_raw_before=bal_raw,
            wallet_raw_after=wallet_after_raw,
            deposit_raw_before=atoken_before,
            deposit_raw_after=atoken_after_raw,
            action_amount_raw=amount_raw,
            reserve_target_usd=reserve_final,
            reserve_abs_usd=reserve_abs,
            reserve_percent=reserve_pct_value,
            available_usd=available_usd,
            min_stake_raw=min_units,
            result="simulated",
        )
        _emit_status("yield:collect", status)
        log.info(
            "[dry-run] would deposit %s to Aave | wallet %s -> %s | deposits %s -> %s | reserve target=%s",
            _fmt_usd_optional(status.get("action_amount_usd")),
            _fmt_usd_optional(status.get("wallet_usd_before")),
            _fmt_usd_optional(status.get("wallet_usd_after")),
            _fmt_usd_optional(status.get("deposit_usd_before")),
            _fmt_usd_optional(status.get("deposit_usd_after")),
            _fmt_usd_optional(status.get("reserve_target_usd")),
        )
        try:
            YIELD_DEPOSITS_TOTAL.labels("aave", "dry_run").inc()
        except Exception:
            pass
        try:
            if conn is not None:
                insert_yield_op(
                    conn,
                    ts_iso=datetime.now(timezone.utc).isoformat(),
                    provider="aave",
                    op="deposit",
                    asset=asset_clean,
                    amount_raw=amount_raw,
                    mode="dry_run",
                    error=None,
                    wallet_raw_before=bal_raw,
                    atoken_raw_before=atoken_before,
                    wallet_raw_after=wallet_after_raw,
                    atoken_raw_after=atoken_after_raw,
                    tx_hash=None,
                )
        except Exception:
            pass
        try:
            notify_discord(
                "yield",
                (
                    "[yield] DRY-RUN deposit "
                    f"{_fmt_usd_optional(status.get('action_amount_usd'))} USDC to Aave | "
                    f"wallet {_fmt_usd_optional(status.get('wallet_usd_before'))} -> {_fmt_usd_optional(status.get('wallet_usd_after'))} | "
                    f"aToken {_fmt_usd_optional(status.get('deposit_usd_before'))} -> {_fmt_usd_optional(status.get('deposit_usd_after'))} | "
                    f"reserve target {_fmt_usd_optional(status.get('reserve_target_usd'))}"
                ),
                extra=status,
            )
        except Exception:
            pass
        return

    try:
        provider.deposit_raw(amount_raw)
        wallet_after_raw = int(provider.get_wallet_balance_raw())
        atoken_after_raw = int(provider.get_deposit_balance_raw())
        status = _yield_status(
            action="deposit",
            asset=asset_clean,
            mode=mode,
            stage="completed",
            wallet_raw_before=bal_raw,
            wallet_raw_after=wallet_after_raw,
            deposit_raw_before=atoken_before,
            deposit_raw_after=atoken_after_raw,
            action_amount_raw=amount_raw,
            reserve_target_usd=reserve_final,
            reserve_abs_usd=reserve_abs,
            reserve_percent=reserve_pct_value,
            available_usd=available_usd,
            min_stake_raw=min_units,
            result="success",
        )
        _emit_status("yield:collect", status)
        log.info(
            "deposited %s to Aave | wallet %s -> %s | deposits %s -> %s | reserve target=%s",
            _fmt_usd_optional(status.get("action_amount_usd")),
            _fmt_usd_optional(status.get("wallet_usd_before")),
            _fmt_usd_optional(status.get("wallet_usd_after")),
            _fmt_usd_optional(status.get("deposit_usd_before")),
            _fmt_usd_optional(status.get("deposit_usd_after")),
            _fmt_usd_optional(status.get("reserve_target_usd")),
        )
        try:
            YIELD_DEPOSITS_TOTAL.labels("aave", "live").inc()
        except Exception:
            pass
        try:
            if conn is not None:
                insert_yield_op(
                    conn,
                    ts_iso=datetime.now(timezone.utc).isoformat(),
                    provider="aave",
                    op="deposit",
                    asset=asset_clean,
                    amount_raw=amount_raw,
                    mode="live",
                    error=None,
                    wallet_raw_before=bal_raw,
                    atoken_raw_before=atoken_before,
                    wallet_raw_after=wallet_after_raw,
                    atoken_raw_after=atoken_after_raw,
                    tx_hash=None,
                )
        except Exception:
            pass
        try:
            notify_discord(
                "yield",
                (
                    "[yield] deposited "
                    f"{_fmt_usd_optional(status.get('action_amount_usd'))} USDC to Aave | "
                    f"wallet {_fmt_usd_optional(status.get('wallet_usd_before'))} -> {_fmt_usd_optional(status.get('wallet_usd_after'))} | "
                    f"aToken {_fmt_usd_optional(status.get('deposit_usd_before'))} -> {_fmt_usd_optional(status.get('deposit_usd_after'))} | "
                    f"reserve target {_fmt_usd_optional(status.get('reserve_target_usd'))}"
                ),
                extra=status,
            )
        except Exception:
            pass
    except Exception as exc:  # pragma: no cover - depends on chain state
        log.error("yield:collect deposit error: %s", exc)
        error_context = _yield_status(
            action="deposit",
            asset=asset_clean,
            mode=mode,
            stage="completed",
            wallet_raw_before=bal_raw,
            deposit_raw_before=atoken_before,
            action_amount_raw=amount_raw,
            reserve_target_usd=reserve_final,
            reserve_abs_usd=reserve_abs,
            reserve_percent=reserve_pct_value,
            available_usd=available_usd,
            min_stake_raw=min_units,
            result="error",
            error=str(exc),
        )
        _emit_status("yield:collect", error_context)
        try:
            YIELD_ERRORS_TOTAL.labels("deposit").inc()
        except Exception:
            pass
        try:
            if conn is not None:
                insert_yield_op(
                    conn,
                    ts_iso=datetime.now(timezone.utc).isoformat(),
                    provider="aave",
                    op="deposit",
                    asset=asset_clean,
                    amount_raw=amount_raw,
                    mode="live",
                    error=str(exc),
                    wallet_raw_before=bal_raw,
                    atoken_raw_before=atoken_before,
                    wallet_raw_after=None,
                    atoken_raw_after=None,
                    tx_hash=None,
                )
        except Exception:
            pass
        try:
            notify_discord(
                "yield",
                f"[yield] deposit error: {exc}",
                severity="error",
                extra=error_context,
            )
        except Exception:
            pass


@app.command("yield:withdraw")
@app.command("yield_withdraw")
def yield_withdraw(
    asset: str = "USDC",
    amount_usd: float | None = None,
    all_excess: bool = False,
    reserve_usd: float | None = None,
    help_verbose: bool = False,
) -> None:
    """Withdraw USDC from Aave v3 Pool back into the wallet.

    Structured status updates mirror the planning and results of the withdrawal
    so users can track wallet balances, reserve targets, and executed amounts
    across log output and Discord notifications.
    """

    if help_verbose:
        app.print_verbose_help_for("yield:withdraw")
        raise SystemExit(0)

    asset_clean = (asset or "").strip().upper()
    if asset_clean != "USDC":
        log.error("yield:withdraw supports USDC only for now")
        return

    try:
        start_metrics_server(settings.prom_port)
    except Exception:
        pass

    provider = AaveProvider(settings)
    reserve_abs = (
        float(reserve_usd)
        if reserve_usd is not None
        else float(getattr(settings, "reserve_amount_usd", 0.0))
    )
    reserve_pct_cfg = getattr(settings, "reserve_percent", 0.0)
    try:
        reserve_pct_value = float(reserve_pct_cfg)
    except Exception:
        reserve_pct_value = 0.0
    reserve_pct = reserve_pct_value / 100.0

    try:
        conn = init_db(settings.sqlite_path)
    except Exception:
        conn = None
    bal_raw = int(provider.get_wallet_balance_raw())
    bal_usd = bal_raw / 1_000_000.0
    atoken_before = int(provider.get_deposit_balance_raw())
    reserve_pct_amt = bal_usd * reserve_pct if reserve_pct > 0 else 0.0
    reserve_final = max(reserve_abs, reserve_pct_amt)

    mode = "dry_run" if bool(getattr(settings, "dry_run", True)) else "live"

    if amount_usd is None and not all_excess:
        error_context = _yield_status(
            action="withdraw",
            asset=asset_clean,
            mode=mode,
            stage="skipped",
            wallet_raw_before=bal_raw,
            deposit_raw_before=atoken_before,
            reserve_target_usd=reserve_final,
            reserve_abs_usd=reserve_abs,
            reserve_percent=reserve_pct_value,
            wallet_deficit_usd=max(reserve_final - bal_usd, 0.0),
            result="invalid_arguments",
            reason="missing_amount",
        )
        _emit_status("yield:withdraw", error_context)
        log.error("Specify --amount-usd or --all-excess")
        return

    if all_excess:
        if bal_usd >= reserve_final:
            skip_context = _yield_status(
                action="withdraw",
                asset=asset_clean,
                mode=mode,
                stage="skipped",
                wallet_raw_before=bal_raw,
                deposit_raw_before=atoken_before,
                reserve_target_usd=reserve_final,
                reserve_abs_usd=reserve_abs,
                reserve_percent=reserve_pct_value,
                wallet_deficit_usd=0.0,
                result="reserve_satisfied",
                reason="wallet_above_reserve",
            )
            _emit_status("yield:withdraw", skip_context)
            log.info(
                "nothing to do: wallet >= reserve (%.2f >= %.2f)",
                bal_usd,
                reserve_final,
            )
            return
        target = reserve_final - bal_usd
        atoken_usd = atoken_before / 1_000_000.0
        if atoken_before > 0:
            amount_usd = min(target, atoken_usd)
        else:
            amount_usd = target

    amount_raw = int(max(float(amount_usd or 0.0), 0.0) * 1_000_000)
    plan_context = _yield_status(
        action="withdraw",
        asset=asset_clean,
        mode=mode,
        stage="plan",
        wallet_raw_before=bal_raw,
        deposit_raw_before=atoken_before,
        action_amount_raw=amount_raw,
        reserve_target_usd=reserve_final,
        reserve_abs_usd=reserve_abs,
        reserve_percent=reserve_pct_value,
        wallet_deficit_usd=max(reserve_final - bal_usd, 0.0),
    )
    _emit_status("yield:withdraw", plan_context)

    if amount_raw <= 0:
        skip_context = _yield_status(
            action="withdraw",
            asset=asset_clean,
            mode=mode,
            stage="skipped",
            wallet_raw_before=bal_raw,
            deposit_raw_before=atoken_before,
            action_amount_raw=amount_raw,
            reserve_target_usd=reserve_final,
            reserve_abs_usd=reserve_abs,
            reserve_percent=reserve_pct_value,
            wallet_deficit_usd=max(reserve_final - bal_usd, 0.0),
            result="invalid_amount",
            reason="non_positive_amount",
        )
        _emit_status("yield:withdraw", skip_context)
        log.error("withdraw amount must be positive")
        return

    if mode == "dry_run":
        wallet_after_raw = bal_raw
        atoken_after_raw = atoken_before
        status = _yield_status(
            action="withdraw",
            asset=asset_clean,
            mode=mode,
            stage="completed",
            wallet_raw_before=bal_raw,
            wallet_raw_after=wallet_after_raw,
            deposit_raw_before=atoken_before,
            deposit_raw_after=atoken_after_raw,
            action_amount_raw=amount_raw,
            reserve_target_usd=reserve_final,
            reserve_abs_usd=reserve_abs,
            reserve_percent=reserve_pct_value,
            wallet_deficit_usd=max(reserve_final - bal_usd, 0.0),
            result="simulated",
        )
        _emit_status("yield:withdraw", status)
        log.info(
            "[dry-run] would withdraw %s from Aave | wallet %s -> %s | deposits %s -> %s | reserve target=%s",
            _fmt_usd_optional(status.get("action_amount_usd")),
            _fmt_usd_optional(status.get("wallet_usd_before")),
            _fmt_usd_optional(status.get("wallet_usd_after")),
            _fmt_usd_optional(status.get("deposit_usd_before")),
            _fmt_usd_optional(status.get("deposit_usd_after")),
            _fmt_usd_optional(status.get("reserve_target_usd")),
        )
        try:
            YIELD_WITHDRAWS_TOTAL.labels("aave", "dry_run").inc()
        except Exception:
            pass
        try:
            if conn is not None:
                insert_yield_op(
                    conn,
                    ts_iso=datetime.now(timezone.utc).isoformat(),
                    provider="aave",
                    op="withdraw",
                    asset=asset_clean,
                    amount_raw=amount_raw,
                    mode="dry_run",
                    error=None,
                    wallet_raw_before=bal_raw,
                    atoken_raw_before=atoken_before,
                    wallet_raw_after=wallet_after_raw,
                    atoken_raw_after=atoken_after_raw,
                    tx_hash=None,
                )
        except Exception:
            pass
        try:
            notify_discord(
                "yield",
                (
                    "[yield] DRY-RUN withdraw "
                    f"{_fmt_usd_optional(status.get('action_amount_usd'))} USDC from Aave | "
                    f"wallet {_fmt_usd_optional(status.get('wallet_usd_before'))} -> {_fmt_usd_optional(status.get('wallet_usd_after'))} | "
                    f"aToken {_fmt_usd_optional(status.get('deposit_usd_before'))} -> {_fmt_usd_optional(status.get('deposit_usd_after'))} | "
                    f"reserve target {_fmt_usd_optional(status.get('reserve_target_usd'))}"
                ),
                extra=status,
            )
        except Exception:
            pass
        return

    try:
        provider.withdraw_raw(amount_raw)
        wallet_after_raw = int(provider.get_wallet_balance_raw())
        atoken_after_raw = int(provider.get_deposit_balance_raw())
        status = _yield_status(
            action="withdraw",
            asset=asset_clean,
            mode=mode,
            stage="completed",
            wallet_raw_before=bal_raw,
            wallet_raw_after=wallet_after_raw,
            deposit_raw_before=atoken_before,
            deposit_raw_after=atoken_after_raw,
            action_amount_raw=amount_raw,
            reserve_target_usd=reserve_final,
            reserve_abs_usd=reserve_abs,
            reserve_percent=reserve_pct_value,
            wallet_deficit_usd=max(reserve_final - bal_usd, 0.0),
            result="success",
        )
        _emit_status("yield:withdraw", status)
        log.info(
            "withdrew %s from Aave | wallet %s -> %s | deposits %s -> %s | reserve target=%s",
            _fmt_usd_optional(status.get("action_amount_usd")),
            _fmt_usd_optional(status.get("wallet_usd_before")),
            _fmt_usd_optional(status.get("wallet_usd_after")),
            _fmt_usd_optional(status.get("deposit_usd_before")),
            _fmt_usd_optional(status.get("deposit_usd_after")),
            _fmt_usd_optional(status.get("reserve_target_usd")),
        )
        try:
            YIELD_WITHDRAWS_TOTAL.labels("aave", "live").inc()
        except Exception:
            pass
        try:
            if conn is not None:
                insert_yield_op(
                    conn,
                    ts_iso=datetime.now(timezone.utc).isoformat(),
                    provider="aave",
                    op="withdraw",
                    asset=asset_clean,
                    amount_raw=amount_raw,
                    mode="live",
                    error=None,
                    wallet_raw_before=bal_raw,
                    atoken_raw_before=atoken_before,
                    wallet_raw_after=wallet_after_raw,
                    atoken_raw_after=atoken_after_raw,
                    tx_hash=None,
                )
        except Exception:
            pass
        try:
            notify_discord(
                "yield",
                (
                    "[yield] withdrew "
                    f"{_fmt_usd_optional(status.get('action_amount_usd'))} USDC from Aave | "
                    f"wallet {_fmt_usd_optional(status.get('wallet_usd_before'))} -> {_fmt_usd_optional(status.get('wallet_usd_after'))} | "
                    f"aToken {_fmt_usd_optional(status.get('deposit_usd_before'))} -> {_fmt_usd_optional(status.get('deposit_usd_after'))} | "
                    f"reserve target {_fmt_usd_optional(status.get('reserve_target_usd'))}"
                ),
                extra=status,
            )
        except Exception:
            pass
    except Exception as exc:  # pragma: no cover
        log.error("yield:withdraw error: %s", exc)
        error_context = _yield_status(
            action="withdraw",
            asset=asset_clean,
            mode=mode,
            stage="completed",
            wallet_raw_before=bal_raw,
            deposit_raw_before=atoken_before,
            action_amount_raw=amount_raw,
            reserve_target_usd=reserve_final,
            reserve_abs_usd=reserve_abs,
            reserve_percent=reserve_pct_value,
            wallet_deficit_usd=max(reserve_final - bal_usd, 0.0),
            result="error",
            error=str(exc),
        )
        _emit_status("yield:withdraw", error_context)
        try:
            YIELD_ERRORS_TOTAL.labels("withdraw").inc()
        except Exception:
            pass
        try:
            if conn is not None:
                insert_yield_op(
                    conn,
                    ts_iso=datetime.now(timezone.utc).isoformat(),
                    provider="aave",
                    op="withdraw",
                    asset=asset_clean,
                    amount_raw=amount_raw,
                    mode="live",
                    error=str(exc),
                    wallet_raw_before=bal_raw,
                    atoken_raw_before=atoken_before,
                    wallet_raw_after=None,
                    atoken_raw_after=None,
                    tx_hash=None,
                )
        except Exception:
            pass
        try:
            notify_discord(
                "yield",
                f"[yield] withdraw error: {exc}",
                severity="error",
                extra=error_context,
            )
        except Exception:
            pass


@app.command("yield:watch")
@app.command("yield_watch")
def yield_watch(
    asset: str = "USDC",
    sources: str | None = None,
    interval: float = 60.0,
    apr_hint: float | None = None,
    min_delta_bps: int = 50,
) -> None:
    """Periodically fetch APRs and alert if a better yield is found."""

    def _parse_sources(raw: str | None) -> list[str]:
        if not raw:
            return []
        raw = raw.strip()
        try:
            arr = json.loads(raw)
            if isinstance(arr, list):
                return [str(url) for url in arr]
        except Exception:
            pass
        return [url.strip() for url in raw.split(",") if url.strip()]

    urls = _parse_sources(sources)
    asset_clean = (asset or "").strip().upper() or "USDC"
    target_apr = float(apr_hint) if apr_hint is not None else None
    min_delta = float(min_delta_bps) / 100.0

    log.info(
        "yield:watch asset=%s interval=%.1fs sources=%d min_delta=%.2f%%",
        asset_clean,
        interval,
        len(urls),
        min_delta,
    )

    try:
        start_metrics_server(settings.prom_port)
    except Exception:
        pass

    while True:
        try:
            YIELD_CHECKS_TOTAL.inc()
        except Exception:
            pass

        best_apr = 0.0
        best_provider = None
        for url in urls:
            try:
                if os.path.isfile(url):
                    with open(url, "r", encoding="utf-8") as handle:
                        payload = handle.read()
                elif url.startswith("file://"):
                    with open(url[7:], "r", encoding="utf-8") as handle:
                        payload = handle.read()
                else:
                    with urllib.request.urlopen(url, timeout=10) as resp:
                        payload = resp.read().decode("utf-8")
                data = json.loads(payload)
            except Exception as exc:
                log.warning("yield:watch failed to fetch %s: %s", url, exc)
                continue

            records = data if isinstance(data, list) else [data]
            for rec in records:
                try:
                    provider = str(rec.get("provider", "")).strip()
                    asset_rec = str(rec.get("asset", "")).strip().upper()
                    apr = float(rec.get("apr_percent"))
                except Exception:
                    continue
                if asset_rec != asset_clean:
                    continue
                if apr > best_apr:
                    best_apr = apr
                    best_provider = provider

        try:
            YIELD_APR.labels(asset_clean).set(target_apr or 0.0)
            YIELD_BEST_APR.labels(asset_clean).set(best_apr)
        except Exception:
            pass

        if best_apr and target_apr is not None and best_apr >= target_apr + min_delta:
            try:
                YIELD_ALERTS_TOTAL.labels(asset_clean).inc()
            except Exception:
                pass
            try:
                notify_discord(
                    "yield",
                    (
                        "Better yield available for "
                        f"{asset_clean}: {best_provider} {best_apr:.2f}% >= "
                        f"current {target_apr:.2f}% + {min_delta * 100:.2f}%"
                    ),
                )
            except Exception:
                pass
        time.sleep(interval)


__all__ = ["yield_collect", "yield_withdraw", "yield_watch"]
