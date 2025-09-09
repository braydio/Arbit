# Tips & Tricks for Safe Testing and Tuning

This guide collects practical advice for configuring and operating Arbit safely, starting small, and growing confidence. It focuses on the Strategy section of `.env.example` and common pitfalls. Expect this document to evolve as features mature.
## Index

- [Quick Recommendations](#quick-recommendations)
- [Using the Yield Collector Safely](#using-the-yield-collector-safely)
- [Monitoring APR for Better Yield](#monitoring-apr-for-better-yield)
- [What To Set For Notional (Starter Amount)](#what-to-set-for-notional-starter-amount)
- [Strategy Variables (from .env.example)](#strategy-variables-from-envexample)
- [Practical Workflows](#practical-workflows)
- [What To Watch In Logs and Metrics](#what-to-watch-in-logs-and-metrics)
- [Database Signals for Performance Debugging](#database-signals-for-performance-debugging)
- [Safety & Operational Tips](#safety--operational-tips)
- [Interpreting `markets:limits` Output](#interpreting-marketslimits-output)
- [Extending This Guide](#extending-this-guide)

## Quick Recommendations

- Notional per trade: Start tiny. Paper: `$5–$25`. Real: `$1–$10` above venue minimums.
- Net threshold: Favor safety. Start `15–30 bps` (0.15–0.30%) after fees.
- Max slippage: Keep strict first. Start `5–10 bps` and relax if too many skips.
- Dry run: Keep `true` until you’ve verified end-to-end behavior and logs.

### Forcing a Safe Execution in Fitness

- Add `--simulate` to `fitness` to attempt dry‑run triangle executions and log
  `net%` and `PnL` when conditions are met.
- Add `--dummy-trigger` to inject a single synthetic profitable snapshot on the
  first loop and exercise the execution path end‑to‑end (no real orders).

Example:

```
python -m arbit.cli fitness --venue alpaca --secs 3 --simulate --dummy-trigger
```

This will print one `[sim] Triangle(...) net=... PnL=...` line and update the
database if `--persist` is also specified.

### CLI Help Quick Reference

- Global help: `python -m arbit.cli --help` (summary) or `--help-verbose` (all flags + examples)
- Fitness flags: `--venue`, `--secs`, `--simulate/--no-simulate`, `--persist/--no-persist`, `--dummy-trigger`, `--help-verbose`
- Live flags: `--venue`, `--help-verbose`
- Yield (beta): `yield:collect --asset USDC --reserve-usd <USD> [--min-stake <units>]`; requires `RPC_URL`/`PRIVATE_KEY`.
- Yield watch: `yield:watch --asset USDC --sources <CSV|JSON> --apr-hint <percent> [--interval 60]`.
- Yield withdraw: `yield:withdraw --asset USDC --amount-usd <USD>` or `--all-excess`.

### Using the Yield Collector Safely

- Start in dry-run: keep `DRY_RUN=true` to preview deposit amounts.
- Set a reserve: use `--reserve-usd` or `RESERVE_AMOUNT_USD` to keep cash on hand for fees.
- Respect minimums: deposits occur only if available balance ≥ `MIN_USDC_STAKE`.
- Understand risk: smart contract risk and gas spikes apply; `max_gas_price_gwei` is enforced in `stake.py`.

#### Recommended Yield Settings

- `--reserve-usd`: start with `$20–$50` to cover fees.
- `--min-stake`: default `100 USDC`; raise only after verifying deposits.
- `max_gas_price_gwei`: keep `<=5` to avoid excessive gas costs.
- `--apr-hint`: use your current provider's APR (e.g., `4.5`).
- `--min-delta-bps`: begin with `50` to limit alert noise.

### Monitoring APR for Better Yield

- Start with a single source endpoint to validate parsing; expand to multiple.
- Set `--apr-hint` to your current provider’s APR; use `--min-delta-bps` to reduce alert noise.
- Metrics to watch: `yield_apr_percent`, `yield_best_apr_percent`, `yield_alerts_total`.

## What To Set For Notional (Starter Amount)

- Purpose: Caps the max quote value for a triangle attempt (derived from `AB` ask). Lower = safer losses, fewer fills; higher = larger PnL swings and more exposure.
- Baseline: Begin with the smallest amount that exceeds your venue’s min-notional for the traded symbols. On many venues this is around `$1–$10`, but check your market’s `limits.cost.min`.
- Suggested starting points:
  - Paper/sandbox: `$5–$25` to see activity without skewing logs or limits.
  - Cautious live: `$1–$10`, aligned with exchange minimums and your risk.
  - Increase gradually while monitoring fills, skips, and realized PnL.
- Watch-outs:
  - If set below the venue’s minimum, triangles will skip (`min_notional_*`).
  - Larger notionals amplify slippage and partial-fill risk.
  - Volatile pairs need smaller notional to mitigate adverse moves during the cycle.

## Strategy Variables (from .env.example)

Below are the Strategy settings and how to think about each. Defaults are chosen to be conservative but not inert.

### `NOTIONAL_PER_TRADE_USD`

- Meaning: Upper bound on trade size per triangle, in the quote currency of leg `AB` (assumed USD/USDT/USDC).
- Implications:
  - Too low: Frequent skips due to `min_notional_*`; negligible PnL in tests.
  - Too high: Greater slippage exposure; sharper drawdowns if execution degrades.
- Recommendations:
  - Start small (see “What To Set For Notional”).
  - Scale up only after observing stable simulated PnL and low slippage skips.

### `NET_THRESHOLD_BPS`

- Meaning: Minimum required net profit for a triangle, in basis points, after fees. The engine computes a net estimate with `(1 - taker_fee) ** 3` included.
- Implications:
  - Too low: More attempts, but higher chance real execution underperforms due to slippage and book shift; risk of negative realized PnL.
  - Too high: Fewer (or no) attempts; you may miss marginal but still positive cycles.
- Recommendations:
  - Typical taker fee ≈ 10 bps per leg → fees are already netted in; set threshold to add buffer for slippage and latency.
  - Start `15–30 bps` (0.15–0.30%). For very volatile markets, use `30–50 bps`.
  - Revisit after you have empirical skip/realized PnL data.

### `MAX_SLIPPAGE_BPS`

- Meaning: Per-leg guardrail. If the top-of-book moves against you beyond this threshold between checks and order placement, the leg is skipped.
- Implications:
  - Too tight: Many `slippage_*` skips; fewer or no full cycles.
  - Too loose: More cycles execute, but realized PnL can degrade quickly.
- Recommendations:
  - Start `5–10 bps`. If you see persistent slippage skips with otherwise healthy spreads, consider `10–15 bps`.
  - Use lower values for thin books or during news; raise only with evidence.

### `MAX_OPEN_ORDERS`

- Meaning: Intended concurrency cap for outstanding orders.
- Current state: Not heavily used by the provided `live` loop (orders are placed sequentially as IOC). Treat as a forward-looking safety valve.
- Recommendations:
  - Keep small (e.g., `1–3`). Increase only if/when you add parallelism.

### `DRY_RUN`

- Meaning: Global simulation flag. When `true`, `create_order` synthesizes fills at top-of-book prices; no orders hit the venue.
- Implications:
  - `live` with `DRY_RUN=true` is safe; `false` may place real orders if keys are live.
  - `fitness` is read-only; add `--simulate` to dry-run cycles without touching the venue.
- Recommendations:
  - Keep `true` initially. Flip to `false` only after you’ve observed healthy simulated PnL and acceptable skip patterns.

### `RESERVE_AMOUNT_USD` / `RESERVE_PERCENT`

- Meaning: Hold back capital so the engine never deploys the full account
  balance.
- Implications:
  - Ensures a cushion remains untouched for withdrawals or manual trading.
  - If both are set, the larger resulting reserve is applied.
- Recommendations:
  - Start with a small dollar amount (e.g., `20`) or percentage (e.g., `10`)
    to keep a safety buffer.

## Practical Workflows

- First contact (safe):
  - `python -m arbit.cli fitness --venue kraken --secs 10`
  - Adjust symbols/venue if spreads are empty or symbols unsupported.
- Simulated cycles:
  - `python -m arbit.cli fitness --venue alpaca --secs 10 --simulate`
  - Add `--persist` to save simulated fills into SQLite for post-hoc review.
  - Add `--dummy-trigger` once to force a known-good execution for validation.
- Cautious live:
  - Keep `DRY_RUN=true` first. Observe logs and metrics in parallel.
  - Only after confidence: set `DRY_RUN=false`, use tiny `NOTIONAL_PER_TRADE_USD`.

## What To Watch In Logs and Metrics

- Skips by reason: frequent `slippage_*` → lower notional or slippage; frequent `min_notional_*` → raise notional slightly or pick deeper pairs.
- Spread quality: small bps = deep books; large bps with low depth increase slippage risk.
- Realized PnL (sim/live): look for stability across time and symbols, not just single spikes.

## Database Signals for Performance Debugging

To evaluate the quality of decisions and implementation, the database logs:

- `triangle_attempts`: one row per attempt (success or skip) including
  timestamps, venue, triangle legs, decision (`ok`), estimated edge
  (`net_est`), realized PnL, threshold/slippage/notional settings used,
  latency, skip reasons, top‑of‑book snapshots, and executed base quantity.
- `fills`: enriched with venue, leg (AB/BC/AC), fee rate, TIF/type, notional,
  dry‑run flag, and `attempt_id` linking to the parent attempt.

These provide enough granularity to measure:

- How often triangles meet thresholds vs. are skipped (by reason)
- Latency distribution per venue/triangle
- Slippage impact (via top‑of‑book snapshots and fee rates)
- Realized vs. estimated outcomes across time

## Safety & Operational Tips

- Use paper/sandbox keys first. Never commit secrets; prefer `.env` locally.
- Confirm triangle symbols exist on your venue (and quote assets match expectations).
- Mind rate limits: bursty loops can hit API limits; prefer fewer venues initially.
- Keep system time accurate; large drift can disrupt rate limiting and logs.
- Start Prometheus early (`PROM_PORT`) and capture baselines before changes.
- SQLite path should live in a writeable directory (e.g., `./data/arbit.db`).
- Discord webhook is best-effort; treat alerts as advisory, not critical.

## Interpreting `markets:limits` Output

When you run `python -m arbit.cli markets:limits --venue ...`, you’ll see lines like:

```
ETH/USDT min_cost=0.5 maker=25 bps taker=40 bps
ETH/BTC  min_cost=2e-05 maker=25 bps taker=40 bps
```

- `min_cost`: The exchange’s minimum notional (quote currency) for that market.
  - For `ETH/USDT`, the quote is USDT → `min_cost=0.5` means $0.50 minimum.
  - For `ETH/BTC`, the quote is BTC → `min_cost=2e-05` means 0.00002 BTC.
  - If `min_cost=0`, the adapter/venue did not expose a minimum via ccxt. There may still be other limits (min qty/step sizes). Treat `0` as “unknown” and use conservative notionals until verified.
- `maker`/`taker`: Fees in basis points (1 bps = 0.01%). Taker is relevant since market IOC legs pay taker. Example: `taker=40 bps` = 0.40% per trade leg.

Using this to pick notional:
- Ensure your notional comfortably exceeds `min_cost` for leg `AB` (and generally for all legs). A simple rule: `NOTIONAL_PER_TRADE_USD >= 2 × min_cost(AB)`.
- For quote assets not in USD (e.g., BTC), convert mentally to USD at current rates to sanity-check exposure.

Aliases and Flags
- The CLI accepts both colon `:` and underscore `_` styles for helper commands:
  - `markets:limits` (preferred) or `markets_limits`
  - `config:recommend` (preferred) or `config_recommend`
- Flags marked in help as “optional” are not required; some only apply when specific modes are enabled (e.g., `--persist` is only relevant with `--simulate`).

## Extending This Guide

As features grow (limit orders, partial-fill reconciliation, position hedging, multi-venue routing), add sections here with:

- New setting semantics and safe defaults.
- Failure modes and how to detect them in logs/metrics.
- Step-by-step rollout playbooks (simulate → partial live → full live).
- Troubleshooting checklists for common errors and bad fills.

Contributions welcome—keep changes concise, actionable, and venue-agnostic where possible.
