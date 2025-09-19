"""Verbose help content for the Arbit CLI package."""

from __future__ import annotations

from textwrap import dedent

VERBOSE_GLOBAL_OVERVIEW = dedent(
    """\
    Command reference

    Use ``--help`` for a compact summary of commands.
    Use ``--help-verbose`` either globally for the full catalog or after a command
    to drill into that command's flags, typical output, and operational tips.

    Exchanges: alpaca (native API via alpaca-py), kraken (via CCXT)
    """
)


VERBOSE_COMMAND_HELP: dict[str, str] = {
    "keys:check": dedent(
        """\
        keys:check
          Purpose:
            Validate API credentials by fetching representative market data. Useful when
            onboarding a new venue or verifying trading permissions.
          Key flags:
            --venue TEXT   Exchange to query (default: alpaca). Use --venue kraken for CCXT.
          Usage tips:
            - Run this before live trading to confirm read/trade permissions.
            - Combine with environment variable overrides to test sandbox keys.
          Sample output:
            [alpaca] markets=123 BTC/USDT 60000/60010 (depth preview for a hot market)
        """
    ),
    "fitness": dedent(
        """\
        fitness
          Purpose:
            Monitor bid/ask spreads and triangle candidates without placing orders.
            Ideal for validating venue connectivity and discovering profitable loops.
          Key flags:
            --venue TEXT              Exchange to query (default: alpaca).
            --secs INTEGER            Seconds to run (default: 20).
            --simulate/--no-simulate  Attempt dry-run triangle executions (default: no).
            --persist/--no-persist    Persist simulated fills to SQLite (with --simulate).
            --dummy-trigger           Inject a synthetic profitable triangle for testing.
            --symbols TEXT            CSV of legs to restrict monitored triangles.
            --discord-heartbeat-secs  Emit periodic Discord summaries (0 disables).
          Usage tips:
            - ``--simulate`` logs net% and PnL estimates; pair with ``--persist`` to audit later.
            - ``--dummy-trigger`` is helpful for end-to-end alerting/metrics rehearsals.
            - Pass ``--symbols 'ETH/USDT,BTC/USDT,ETH/BTC'`` to restrict to familiar legs.
            - Discord heartbeats summarize attempts/successes for remote monitoring.
          Sample log lines:
            kraken ETH/USDT spread=0.5 bps
            kraken [sim] Triangle(ETH/USDT, ETH/BTC, BTC/USDT) net=0.15% PnL=0.05 USDT
        """
    ),
    "live": dedent(
        """\
        live
          Purpose:
            Continuously evaluate live triangles and place orders when the net spread beats
            configured thresholds. Intended for production once fitness results look healthy.
          Key flags:
            --venues TEXT         CSV list of venues to trade concurrently (overrides --venue).
            --venue TEXT           Single venue fallback when --venues is omitted (default: alpaca).
            --symbols TEXT         CSV leg filter applied before triangle selection.
            --auto-suggest-top INT Auto-generate a shortlist of triangles when config is empty.
            --attempt-notify       Send Discord updates on every attempt (noisy, opt-in).
          Usage tips:
            - ``--venues`` overrides ``--venue`` and spins up a loop per venue.
            - Confirm balances via the startup banner before trusting executions.
            - ``--symbols`` keeps exposure constrained to pairs you actively monitor.
            - ``--auto-suggest-top`` is useful for quick experiments; persists only for session.
            - Combine with metrics on port 9109 to track cycle latency and realized profit.
          Sample log lines:
            alpaca Triangle(ETH/USDT, ETH/BTC, BTC/USDT) net=0.42% PnL=0.11 USDT
            alpaca heartbeat: dry_run=True attempts=250 successes=3 hit_rate=1.20%
        """
    ),
    "markets:limits": dedent(
        """\
        markets:limits
          Purpose:
            Inspect minimum notionals and maker/taker fees for venue markets.
            Handy when sizing trades or configuring triangle thresholds.
          Key flags:
            --venue TEXT   Exchange to query (default: alpaca).
            --symbols TEXT CSV of symbols to filter (defaults to configured triangle legs).
          Usage tips:
            - Use alongside fitness metrics to correlate spreads versus fee drag.
            - Export results to a spreadsheet for per-symbol what-if analysis.
          Sample output:
            BTC/USDT min_cost=5.0 maker=10 bps taker=10 bps
        """
    ),
    "config:recommend": dedent(
        """\
        config:recommend
          Purpose:
            Suggest starting strategy parameters for a venue based on historical heuristics.
          Key flags:
            --venue TEXT  Exchange to analyze (default: alpaca).
          Usage tips:
            - Treat as a baseline; tune thresholds according to venue-specific slippage.
            - Pair with ``markets:limits`` output to ensure size recommendations clear minimums.
          Sample output:
            Recommend: NOTIONAL_PER_TRADE_USD=10 NET_THRESHOLD_BPS=25 MAX_SLIPPAGE_BPS=8 DRY_RUN=true
        """
    ),
    "fitness:hybrid": dedent(
        """\
        fitness:hybrid
          Purpose:
            Evaluate cross-venue triangles by mixing legs from multiple exchanges without trading.
            Useful for gauging latency penalties or cross-exchange arbitrage headroom.
          Key flags:
            --legs TEXT     CSV of legs (default: ETH/USDT,ETH/BTC,BTC/USDT).
            --venues TEXT   CSV mapping leg=venue (e.g., ETH/USDT=kraken,...).
            --secs INTEGER  Seconds to sample (default: 10).
          Usage tips:
            - Keep expectations modest; liquidity and settlement risk grow across venues.
            - Pair with ``markets:limits`` to ensure proposed legs exist on target venues.
          Notes:
            Estimates only—no simulation or order placement occurs.
        """
    ),
    "config:discover": dedent(
        """\
        config:discover
          Purpose:
            Enumerate supported triangles for a venue via ``load_markets`` and optionally persist
            them into ``.env`` for quick reuse.
          Key flags:
            --venue TEXT     Exchange to inspect (default: kraken).
            --write-env      Write TRIANGLES_BY_VENUE to .env for the venue.
            --env-path TEXT  Location of the .env file (default: .env).
          Usage tips:
            - Capture output under version control to document venue coverage drift.
            - Use ``--write-env`` during onboarding to scaffold configuration quickly.
          Sample output:
            kraken triangles=15 first=ETH/USDT|ETH/BTC|BTC/USDT
        """
    ),
    "yield:collect": dedent(
        """\
        yield:collect
          Purpose:
            Deposit idle USDC into Aave v3 with configurable wallet reserves.
          Key flags:
            --asset TEXT        Asset symbol to deposit (default: USDC).
            --min-stake INTEGER Minimum token units to deposit (defaults from settings).
            --reserve-usd FLOAT Keep this much USD in wallet; reserve_percent also applies.
          Usage tips:
            - Requires RPC_URL and PRIVATE_KEY environment variables; honors global DRY_RUN.
            - Run with ``--help-verbose`` first to confirm assumptions before live funds.
            - Pair with ``yield:watch`` alerts to know when to unwind positions.
          Sample output:
            [dry-run] would deposit 150.00 USDC to Aave (reserve=50.00)
        """
    ),
    "yield:withdraw": dedent(
        """\
        yield:withdraw
          Purpose:
            Withdraw USDC from Aave v3 either by specifying an amount or freeing all excess
            above the configured reserve target.
          Key flags:
            --asset TEXT        Asset symbol (default: USDC).
            --amount-usd FLOAT  Exact USD amount to withdraw.
            --all-excess        Withdraw everything above reserve thresholds.
            --reserve-usd FLOAT Override reserve size when computing ``--all-excess``.
          Usage tips:
            - Honors DRY_RUN; review simulated withdrawal amounts before executing for real.
            - Combine with ``yield:collect`` to rebalance wallet liquidity after profit-taking.
          Sample output:
            [dry-run] would withdraw 75.00 USDC (leaving reserve=50.00)
        """
    ),
    "yield:watch": dedent(
        """\
        yield:watch
          Purpose:
            Poll APR sources and emit Discord alerts when a better yield exceeds thresholds.
          Key flags:
            --asset TEXT        Asset symbol (default: USDC).
            --sources TEXT      CSV or JSON array of {provider, asset, apr_percent} endpoints.
            --interval FLOAT    Poll interval seconds (default: 60).
            --apr-hint FLOAT    Current provider APR baseline for alert comparisons.
            --min-delta-bps INT Minimum APR improvement before alerting (default: 50 bps).
          Usage tips:
            - Configure Discord notifications to surface actionable opportunities quickly.
            - Use ``--sources`` with a local JSON file during development for repeatability.
          Sample output:
            Better yield available for USDC: foo 5.10% >= current 4.50% + 0.50%
        """
    ),
}

__all__ = ["VERBOSE_GLOBAL_OVERVIEW", "VERBOSE_COMMAND_HELP"]
