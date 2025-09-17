# Arbit - Triangular Arbitrage Trading System

A modular Python package for triangular arbitrage trading on cryptocurrency exchanges, with CLI interface, metrics, SQLite persistence, Docker support, and optional DeFi integration.

## ⚠️ IMPORTANT SAFETY NOTICE

> **WARNING**: This software can place real trades and lose real money.
> 
> - The `live` command **WILL place real orders** if your API keys have trading permissions
> - Always start with `fitness` mode (read-only) for testing connectivity
> - Use sandbox/paper trading environments when available (see `.env.example`)
> - Current limitations: fees/slippage/partial fills not fully modeled
> - **This is not financial advice. Use at your own risk.**
- **NOT READY FOR PRODUCTION TRADING** - see [WARP.md](docs/WARP.md#safety-and-risk-management) for current limitations

## What It Does

Arbit monitors triangular arbitrage opportunities across cryptocurrency exchanges by tracking price differences in three-legged cycles like:

**USDT → ETH → BTC → USDT**
- Buy ETH with USDT (`ETH/USDT`)
- Sell ETH for BTC (`ETH/BTC`) 
- Sell BTC for USDT (`BTC/USDT`)

New candidates (enabled by default on Kraken):

**USDT → SOL → BTC → USDT**
- Buy SOL with USDT (`SOL/USDT`)
- Sell SOL for BTC (`SOL/BTC`)
- Sell BTC for USDT (`BTC/USDT`)

Why SOL? High daily volume and active BTC cross provide frequent micro-inefficiencies with sufficient depth. This triangle is included by default on Kraken. Some venues (e.g., Alpaca) may not list `SOL/BTC`; use `--symbols` filtering or override triangles in `.env`. Always verify symbols exist on your venue (`keys:check`) and keep thresholds conservative.

Another stablecoin triangle now included by default on Kraken:

**USDT → DAI → ETH → USDT**
- Swap USDT to DAI (`DAI/USDT`)
- Swap DAI to ETH (`ETH/DAI`)
- Swap ETH back to USDT (`ETH/USDT`)

Rationale: Tight spreads on `DAI/USDT` and `ETH/USDT` with generally adequate depth on `ETH/DAI` make this a reasonable candidate. If your venue shows stronger depth on USDC, consider replacing with `USDT → USDC → ETH → USDT` instead.

Also enabled by default on Kraken where liquidity is strong:

**USDT → USDC → ETH → USDT**
- Swap USDT to USDC (`USDC/USDT`)
- Swap USDC to ETH (`ETH/USDC`)
- Swap ETH back to USDT (`ETH/USDT`)

Rationale: `USDC/USDT` and `ETH/USDC` are typically very liquid on Kraken with tight spreads, offering frequent micro-inefficiencies while keeping inventory risk low.

**Core Features:**
- **Read-only monitoring** with `fitness` command (safe for testing)
- **Live execution** with `live` command (⚠️ places real orders)
- **Prometheus metrics** for monitoring and alerting
- **SQLite persistence** for trade history
- **Docker support** with multi-venue deployment
- **WebSocket streaming** with automatic REST fallback
- **Supported exchanges**: Alpaca (native), Kraken (via CCXT)

## Project Structure

- `arbit/`: core package
  - `engine/`: triangle math and execution
  - `adapters/`: exchange connectors (CCXT and Alpaca)
  - `metrics/`: Prometheus exporters
  - `persistence/`: SQLite helpers
  - `cli.py`: Typer CLI entry point
- `tests/`: pytest suite (`test_*.py`)
- `data/`: local data/DB (gitignored)
- `scripts/`: helper scripts
- `Dockerfile`, `docker-compose.yml`: containerization
- `docs/`: extended docs (`ROADMAP.md`, `WARP.md`, `ROADMAP_PHASE_II.md`)
- `TIPS_TRICKS.md` and `TIPS_TRICKS.html`: operational tips

### CLI Modes at a Glance

| Mode        | Purpose                                                         | Example log line                             |
|-------------|-----------------------------------------------------------------|----------------------------------------------|
| `fitness`   | Read-only spread sampling to verify connectivity                | `kraken ETH/USDT spread=0.5 bps`             |
| `live`      | Execute trades when triangles meet profit thresholds            | `alpaca Triangle(...) net=0.15% PnL=0.05`    |
| `keys:check`| Validate exchange keys and permissions                          | `[alpaca] markets=123 BTC/USDT 60000/60010`  |

Run `python -m arbit.cli --help-verbose` for the full catalog, or append
`--help-verbose` to a command (for example, `python -m arbit.cli fitness --help-verbose`)
to drill into a single command's flags, sample output, and operational tips.

### CLI Help

- Global: `--help` (summary), `--help-verbose` (detailed catalog or command-specific when appended)
- `fitness` flags: `--venue`, `--secs`, `--simulate/--no-simulate`, `--persist/--no-persist`, `--dummy-trigger`, `--help-verbose`
- `live` flags: `--venue`, `--help-verbose`
- `live:multi` flags: `--venues`, `--symbols`, `--auto-suggest-top`
  - Example: `python -m arbit.cli live:multi --venues alpaca,kraken`
  - Or use `./scripts/run_live_multi.sh` with `VENUES`, `SYMBOLS`, `AUTO_SUGGEST_TOP`
- Helpers: `keys:check`, `markets:limits --venue --symbols`, `config:recommend --venue`
- Yield: `yield:collect --asset USDC --reserve-usd 50` (beta, on-chain)
- Yield watch: `yield:watch --asset USDC --sources <CSV|JSON> --interval 60 --apr-hint 4.5`
- Yield withdraw: `yield:withdraw --asset USDC --amount-usd 75` or `--all-excess`

See [WARP.md](docs/WARP.md) for comprehensive documentation, architecture details, and development roadmap.

## Quick Start

```bash
# Set up virtual environment
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
python -m pip install -U pip
pip install alpaca-py ccxt pydantic typer prometheus-client orjson websockets pytest

# Configure API credentials (see Configuration section below)
export ARBIT_API_KEY=your_venue_api_key
export ARBIT_API_SECRET=your_venue_api_secret

# Test connectivity (READ-ONLY, safe)
python -m arbit.cli fitness --venue kraken --secs 10

# ⚠️ CAUTION: Live trading (places real orders if keys allow)
# Metrics port configured via PROM_PORT env var (default: 9109)
python -m arbit.cli live --venue alpaca

# Check metrics
curl http://localhost:9109/metrics
```

💡 **First time?** Use `fitness` command first to verify connectivity. See [WARP.md](docs/WARP.md) for detailed explanations and safety practices.

### Kraken Promotion Helper

Need to complete Kraken's "$20 in BTC" welcome promo that requires at least $50 in trading volume on a non-stablecoin asset? The Typer helper below plans a qualifying trade and defaults to a safe dry run:

```bash
# Preview the plan (no orders placed)
python -m arbit.promo.kraken trade --usd-amount 55 --base ETH --quote USD

# Execute the trade once you're ready
export DRY_RUN=false  # required for live orders
python -m arbit.promo.kraken trade --usd-amount 55 --base ETH --quote USD --execute
```

Key safeguards:

- Rejects stablecoin bases (e.g., USDC, USDT) so the trade qualifies.
- Verifies the notional exceeds $50 after rounding to Kraken's lot size.
- Sells the asset back to the quote currency by default to keep exposure flat (use `--hold` to keep it).
- Requires both `--execute` **and** `DRY_RUN=false` to place real orders.

## Installation

**Requirements:** Python 3.10+ recommended

```bash
# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt pytest

# Optional: DeFi integration
pip install web3

```

See [WARP.md Development Workflow](docs/WARP.md#development-workflow) for complete setup instructions. For practical guidance on safe tuning and starter values, see [TIPS_TRICKS.md](TIPS_TRICKS.md).

## Configuration

Arbit uses Pydantic Settings with `ARBIT_` environment prefix and `.env` file support.

### Core Settings

```bash
# Exchange credentials (required)
export ARBIT_API_KEY=your_venue_api_key
export ARBIT_API_SECRET=your_venue_api_secret

# Trading parameters
export NET_THRESHOLD_BPS=10          # minimum profit threshold (basis points)
export NOTIONAL_PER_TRADE_USD=200    # maximum trade size
export RESERVE_AMOUNT_USD=0          # funds to keep in reserve
export RESERVE_PERCENT=0             # % of balance to reserve
export SQLITE_PATH=./data/arbit.db   # database file path
export PROM_PORT=9109               # metrics server port

# RESERVE_AMOUNT_USD and RESERVE_PERCENT let you keep part of the account
# balance untouched during arbitrage. Set one or both depending on your risk
# tolerance.

# Create data directory
mkdir -p data

# Market data freshness controls (optional)
# Max age of any leg's order book before skipping the attempt (ms)
export MAX_BOOK_AGE_MS=1500
# Try a quick REST fetch to refresh stale legs before skipping (reduces stale_book)
export REFRESH_ON_STALE=true
# Min gap between refreshes per symbol (ms)
export STALE_REFRESH_MIN_GAP_MS=150

### Fee overrides for CCXT venues

Most CCXT exchanges expose maker/taker tiers through their metadata, but some
accounts qualify for custom discounts (e.g., promotional or volume-based
pricing). Set ``FEE_OVERRIDES`` with a JSON blob to supply per-venue, per-symbol
fees in basis points so Arbit's net calculation matches your tier:

```bash
export FEE_OVERRIDES='{"kraken":{"ETH/USDT":{"taker_bps":0,"maker_bps":0},"BTC/USDT":{"taker_bps":5}}}'
```

The keys are lowercase venues and uppercase symbols. ``maker_bps``/``taker_bps``
accept numbers in basis points (``5`` → ``0.0005``). You can also provide
decimal ``maker``/``taker`` fields if you already know the fraction. Optional
``"*"`` entries apply to every symbol on the venue.

💡 **Tip:** zero-fee tiers radically improve the net estimate. Reduce
``NET_THRESHOLD_BPS`` to keep the execution guard realistic once overrides are
in place.
```

### Per-Venue Configuration

For multiple exchanges, use venue-specific variables:

```bash
# Alpaca (paper trading recommended)
export ALPACA_API_KEY=your_alpaca_key
export ALPACA_API_SECRET=your_alpaca_secret
export ALPACA_BASE_URL=https://paper-api.alpaca.markets  # Paper trading
export ALPACA_WS_CRYPTO_URL=wss://stream.data.alpaca.markets/v1beta3/crypto/us  # optional
export ALPACA_MAP_USDT_TO_USD=true  # treat /USDT pairs as /USD

# Kraken
export KRAKEN_API_KEY=your_kraken_key
export KRAKEN_API_SECRET=your_kraken_secret

# Discord notifications (optional)
export DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...   # enable alerts
export DISCORD_HEARTBEAT_SECS=60                                  # live periodic summary
export DISCORD_TRADE_NOTIFY=false                                  # trade-only alerts
export DISCORD_ATTEMPT_NOTIFY=false                                # per-attempt alerts (noisy)
export DISCORD_MIN_NOTIFY_INTERVAL_SECS=10                         # rate limit seconds
```

### Using .env Files

Copy `.env.example` to `.env` and customize:

```bash
cp .env.example .env
# Edit .env with your credentials
```

See [WARP.md Configuration](docs/WARP.md#configuration-and-environment) for complete variable reference.

## Usage

### Fitness Mode (Read-Only Testing)

Safely test connectivity and monitor spreads without placing orders:

```bash
# Test Kraken connectivity for 20 seconds
python -m arbit.cli fitness --venue kraken --secs 20

# Quick Alpaca test
python -m arbit.cli fitness --venue alpaca --secs 5
```

On startup, current account balances for supported venues (Alpaca, Kraken) are
logged. Typical log line: ``kraken ETH/USDT spread=0.5 bps`` where ``spread`` is
the best ask minus best bid expressed in basis points (1 bps = 0.01%). Smaller
spreads generally indicate deeper liquidity. Use ``--help-verbose`` for more
output guidance.

Optionally simulate dry-run triangle executions and log simulated PnL:

```bash
python -m arbit.cli fitness --venue alpaca --secs 5 --simulate
# Persist simulated fills to SQLite
python -m arbit.cli fitness --venue alpaca --secs 5 --simulate --persist
# Force a safe synthetic execution to exercise the path
python -m arbit.cli fitness --venue alpaca --secs 3 --simulate --dummy-trigger
```

When ``--dummy-trigger`` is set (fitness mode only), the CLI injects a single
synthetic top-of-book snapshot that yields a profitable triangle and records a
dry-run execution. This is useful to validate your end-to-end flow (persistence
and logging) without relying on market conditions.

### Live Trading (⚠️ PLACES REAL ORDERS)

**WARNING**: Only use with tiny amounts and proper risk management!

```bash
# Live trading (runs continuously until stopped)
export PROM_PORT=9109  # Optional: set metrics port
python -m arbit.cli live --venue alpaca

# With different venue
python -m arbit.cli live --venue kraken
```

At launch, the CLI logs current balances for supported venues. A typical
execution log looks like
``alpaca Triangle(ETH/USDT, ETH/BTC, BTC/USDT) net=0.15% PnL=0.05 USDT``. Here
``net`` denotes the estimated profit after fees for the triangle and ``PnL``
shows realized profit in USDT. Invoke the command with ``--help-verbose`` to see
these explanations from the CLI itself.

### Monitoring & Metrics

Prometheus metrics are exposed on port 9109 by default:

```bash
# View metrics
curl http://localhost:9109/metrics

# Key metrics: orders_total, fills_total, profit_total_usdt
```

### WebSocket Streaming Example

Stream live order books with the native Alpaca adapter:

```python
import asyncio
from arbit.adapters.alpaca_adapter import AlpacaAdapter

async def main():
    adapter = AlpacaAdapter()
    async for sym, book in adapter.orderbook_stream(["BTC/USDT"], depth=1):
        print(sym, book)
        break
    await adapter.close()

asyncio.run(main())
```

**Supported Venues**: `alpaca`, `kraken`

**Note**: Ensure triangle symbols exist on your chosen venue (e.g., ETH/USDT, ETH/BTC, BTC/USDT; SOL/USDT, SOL/BTC, BTC/USDT on supported venues like Kraken). See [WARP.md CLI Commands](docs/WARP.md#cli-commands) for full documentation.

Customizing triangles (advanced): set `TRIANGLES_BY_VENUE` as JSON in `.env` to override defaults, e.g.
```
TRIANGLES_BY_VENUE={
  "alpaca": [["ETH/USDT","ETH/BTC","BTC/USDT"],["SOL/USDT","SOL/BTC","BTC/USDT"]],
  "kraken": [["ETH/USDC","ETH/BTC","BTC/USDC"]]
}
```

## Persistence

SQLite is used by default (see ``SQLITE_PATH``). In addition to the existing
``triangles`` and ``fills`` tables, Arbit records per-attempt data in
``triangle_attempts`` to help gauge system performance:

- triangle_attempts: ts_iso, venue, legs, ok, net_est, realized_usdt,
  threshold_bps, notional_usd, slippage_bps, dry_run, latency_ms, skip_reasons,
  top-of-book (ab/bc/ac bid/ask) and qty_base.
- fills now include: venue, leg (AB/BC/AC), tif, order_type, fee_rate,
  notional, dry_run, and attempt_id linking back to the attempt.

These additions are backwards-compatible; existing columns and tests remain
unchanged.

### Setup Helpers

Inspect market limits and fees for sizing notional:

```bash
python -m arbit.cli markets:limits --venue alpaca --symbols ETH/USDT,BTC/USDT
```

Get recommended starter Strategy settings based on venue data:

```bash
python -m arbit.cli config:recommend --venue alpaca
```

## Docker Quick Start

```bash
# Configure environment
cp .env.example .env
# Edit .env with your API keys

# Deploy both venues
docker compose up -d --build

# View logs
docker compose logs -f
```

**Important**: Docker containers run the `live` command and **will place real orders** if your API keys have trading permissions. Review `docker-compose.yml` and use paper/sandbox keys.

## Optional: DeFi Integration (Aave)

The `stake.py` script provides Aave v3 USDC staking integration:

```bash
# Required environment variables
export RPC_URL=https://your-rpc-endpoint
export PRIVATE_KEY=0x...  # ⚠️ Use test keys only
export ARBIT_USDC_ADDRESS=0x...  # Chain-specific USDC
export ARBIT_POOL_ADDRESS=0x...  # Aave v3 Pool

# Optional ABI paths (defaults provided)
export ARBIT_USDC_ABI_PATH=erc20.json
export ARBIT_POOL_ABI_PATH=aave_pool.json
```

**⚠️ EXTREME CAUTION**: Never use mainnet private keys in development. See [WARP.md DeFi Integration](docs/WARP.md#defi-integration) for safety practices.

### Yield Collector (Beta)

Use the CLI to deposit idle on-chain USDC to Aave while keeping a wallet reserve. Honors global `DRY_RUN` (logs only):

```
# Dry-run preview (no txs): keeps $50 in wallet, deposits rest if >= min stake
python -m arbit.cli yield:collect --asset USDC --reserve-usd 50

# Live (DRY_RUN=false): executes approve + supply using stake.py checks
export DRY_RUN=false
python -m arbit.cli yield:collect --asset USDC --reserve-usd 50
```

Requirements:
- Env: `RPC_URL`, `PRIVATE_KEY`
- Settings: `usdc_address`, `pool_address`, `min_usdc_stake`, `max_gas_price_gwei`, `reserve_amount_usd`, `reserve_percent`
- Optional: `atoken_address` (aToken for USDC) enables precise aToken balance reads for withdrawals.
- Asset: USDC (6 decimals) only for now
- Dependency: `web3` (install with `pip install web3` or via `requirements.txt`)

### Yield Watch (APR Monitoring)

Continuously polls APR endpoints and alerts if a better yield is available.

```
# CSV of URLs or JSON array; supports local files too
python -m arbit.cli yield:watch --asset USDC --sources "https://api.example/apr.json,apr_local.json"

# Provide baseline APR for current provider to trigger alerts when best APR exceeds baseline by delta
python -m arbit.cli yield:watch --asset USDC --sources '["https://api.example/apr.json"]' --apr-hint 4.5 --min-delta-bps 50
```

Metrics:
- `yield_apr_percent{provider,asset}` and `yield_best_apr_percent{asset}`
- `yield_checks_total`, `yield_alerts_total{asset}`
- Deposit counters: `yield_deposits_total{provider,mode}`; errors: `yield_errors_total{stage}`
- The metrics server runs on `PROM_PORT` (default `9109`).

## Troubleshooting

**Common Issues:**

- **Credentials**: Ensure `ARBIT_API_KEY`/`ARBIT_API_SECRET` match your `--venue`
- **Symbols**: Verify triangle legs exist (some venues use `ETH/BTC` vs `BTC/ETH`)
- **Rate limits**: Reduce polling frequency if getting rate limited
- **Data directory**: Run `mkdir -p data` or set `SQLITE_PATH` to custom location
- **Metrics**: Check port availability and Docker port mapping
- **Dependencies**: Ensure all packages installed in active venv

See [WARP.md Troubleshooting](docs/WARP.md#common-issues-and-troubleshooting) for detailed solutions.

## FAQ

**Q: Does this place actual trades?**
A: `fitness` is read-only. `live` **WILL place real orders** if keys have trading permissions.

**Q: Which exchanges are supported?**  
A: Currently Alpaca (native) and Kraken (via CCXT). More exchanges can be added.

**Q: How accurate are profit estimates?**
A: Estimates assume perfect execution at top-of-book prices. Real trading involves slippage, fees, and partial fills.

**Q: Do I need API keys?**
A: Yes, even for `fitness` mode to access order book data.

**Q: Is this ready for production?**
A: **NO**. This is development/research software. See [safety warnings](#%EF%B8%8F-important-safety-notice) above.

## For Developers

This README provides user-focused documentation. For comprehensive technical details:

- **[WARP.md](docs/WARP.md)** - Complete documentation (architecture, roadmap, development)
- **Tests**: `pytest -q`

## Acknowledgments

Built with [alpaca-py](https://github.com/alpacahq/alpaca-py) for native Alpaca connectivity, [CCXT](https://github.com/ccxt/ccxt) for other exchanges, [Pydantic](https://pydantic-docs.helpmanual.io/) for configuration, and [Typer](https://typer.tiangolo.com/) for CLI interface.

---

📖 **Complete Documentation**: [WARP.md](docs/WARP.md)  
⚠️ **Safety First**: Always test with paper trading and minimal amounts
