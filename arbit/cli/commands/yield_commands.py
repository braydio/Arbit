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


@app.command("yield:collect")
@app.command("yield_collect")
def yield_collect(
    asset: str = "USDC",
    min_stake: int | None = None,
    reserve_usd: float | None = None,
    help_verbose: bool = False,
) -> None:
    """Deposit idle stablecoin into Aave v3 (beta, USDC only)."""

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
        reserve_pct = float(reserve_pct_cfg) / 100.0
    except Exception:
        reserve_pct = 0.0
    reserve_pct_amt = bal_usd * reserve_pct if reserve_pct > 0 else 0.0
    reserve_final = max(reserve_abs, reserve_pct_amt)

    available_usd = max(bal_usd - reserve_final, 0.0)
    amount_raw = int(available_usd * 1_000_000)
    min_units = (
        int(min_stake)
        if min_stake is not None
        else int(getattr(settings, "min_usdc_stake", 1_000_000))
    )

    if amount_raw < min_units:
        log.info(
            "nothing to do: balance=%.2f USDC reserve=%.2f min_stake=%.2f",
            bal_usd,
            reserve_final,
            min_units / 1_000_000.0,
        )
        return

    if bool(getattr(settings, "dry_run", True)):
        log.info(
            "[dry-run] would deposit %.2f USDC to Aave (reserve=%.2f)",
            amount_raw / 1_000_000.0,
            reserve_final,
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
                    wallet_raw_after=bal_raw,
                    atoken_raw_after=atoken_before,
                    tx_hash=None,
                )
        except Exception:
            pass
        try:
            notify_discord(
                "yield",
                (
                    "[yield] DRY-RUN deposit "
                    f"{fmt_usd(amount_raw / 1_000_000.0)} USDC to Aave | reserve {fmt_usd(reserve_final)} USDC"
                ),
            )
        except Exception:
            pass
        return

    try:
        provider.deposit_raw(amount_raw)
        log.info(
            "deposited %.2f USDC to Aave (kept reserve=%.2f)",
            amount_raw / 1_000_000.0,
            reserve_final,
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
                    wallet_raw_after=int(provider.get_wallet_balance_raw()),
                    atoken_raw_after=int(provider.get_deposit_balance_raw()),
                    tx_hash=None,
                )
        except Exception:
            pass
        try:
            notify_discord(
                "yield",
                (
                    "[yield] deposited "
                    f"{fmt_usd(amount_raw / 1_000_000.0)} USDC to Aave | reserve {fmt_usd(reserve_final)} USDC"
                ),
            )
        except Exception:
            pass
    except Exception as exc:  # pragma: no cover - depends on chain state
        log.error("yield:collect deposit error: %s", exc)
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


@app.command("yield:withdraw")
@app.command("yield_withdraw")
def yield_withdraw(
    asset: str = "USDC",
    amount_usd: float | None = None,
    all_excess: bool = False,
    reserve_usd: float | None = None,
    help_verbose: bool = False,
) -> None:
    """Withdraw USDC from Aave v3 Pool back into the wallet."""

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
        reserve_pct = float(reserve_pct_cfg) / 100.0
    except Exception:
        reserve_pct = 0.0

    try:
        conn = init_db(settings.sqlite_path)
    except Exception:
        conn = None
    bal_raw = int(provider.get_wallet_balance_raw())
    bal_usd = bal_raw / 1_000_000.0
    reserve_pct_amt = bal_usd * reserve_pct if reserve_pct > 0 else 0.0
    reserve_final = max(reserve_abs, reserve_pct_amt)

    if amount_usd is None and not all_excess:
        log.error("Specify --amount-usd or --all-excess")
        return

    if all_excess:
        atoken_raw = provider.get_deposit_balance_raw()
        atoken_usd = atoken_raw / 1_000_000.0
        if bal_usd >= reserve_final:
            log.info(
                "nothing to do: wallet >= reserve (%.2f >= %.2f)",
                bal_usd,
                reserve_final,
            )
            return
        target = reserve_final - bal_usd
        if atoken_raw > 0:
            amount_usd = min(target, atoken_usd)
        else:
            amount_usd = target

    amount_raw = int(max(float(amount_usd or 0.0), 0.0) * 1_000_000)
    if amount_raw <= 0:
        log.error("withdraw amount must be positive")
        return

    if bool(getattr(settings, "dry_run", True)):
        log.info(
            "[dry-run] would withdraw %.2f USDC from Aave", amount_raw / 1_000_000.0
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
                    atoken_raw_before=int(provider.get_deposit_balance_raw()),
                    wallet_raw_after=bal_raw,
                    atoken_raw_after=int(provider.get_deposit_balance_raw()),
                    tx_hash=None,
                )
        except Exception:
            pass
        try:
            notify_discord(
                "yield",
                (
                    "[yield] DRY-RUN withdraw "
                    f"{fmt_usd(amount_raw / 1_000_000.0)} USDC from Aave"
                ),
            )
        except Exception:
            pass
        return

    try:
        provider.withdraw_raw(amount_raw)
        log.info("withdrew %.2f USDC from Aave", amount_raw / 1_000_000.0)
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
                    atoken_raw_before=int(provider.get_deposit_balance_raw()),
                    wallet_raw_after=int(provider.get_wallet_balance_raw()),
                    atoken_raw_after=int(provider.get_deposit_balance_raw()),
                    tx_hash=None,
                )
        except Exception:
            pass
        try:
            notify_discord(
                "yield",
                (
                    "[yield] withdrew "
                    f"{fmt_usd(amount_raw / 1_000_000.0)} USDC from Aave"
                ),
            )
        except Exception:
            pass
    except Exception as exc:  # pragma: no cover
        log.error("yield:withdraw error: %s", exc)
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
                    atoken_raw_before=int(provider.get_deposit_balance_raw()),
                    wallet_raw_after=None,
                    atoken_raw_after=None,
                    tx_hash=None,
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
