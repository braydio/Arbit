# Arbit - Triangular Arbitrage Trading System

A modular Python package for triangular arbitrage trading on cryptocurrency exchanges, with CLI interface, metrics, SQLite persistence, Docker support, and optional DeFi integration.

## ⚠️ IMPORTANT SAFETY NOTICE

> **WARNING**: This software can place real trades and lose real money.
> 
> - The `live` command **WILL place real orders** if your API keys have trading permissions
> - Always start with `fitness` mode (read-only) for testing connectivity
> - Use sandbox/paper trading environments when available (see `.env.example`)
> - Current limitations: no explicit dry-run toggle, fees/slippage/partial fills not fully modeled
> - **This is not financial advice. Use at your own risk.**
> - **NOT READY FOR PRODUCTION TRADING** - see [WARP.md](WARP.md#safety-and-risk-management) for current limitations

## What It Does

Arbit monitors triangular arbitrage opportunities across cryptocurrency exchanges by tracking price differences in three-legged cycles like:

**USDT → ETH → BTC → USDT**
- Buy ETH with USDT (`ETH/USDT`)
- Sell ETH for BTC (`ETH/BTC`) 
- Sell BTC for USDT (`BTC/USDT`)

**Core Features:**
- **Read-only monitoring** with `fitness` command (safe for testing)
- **Live execution** with `live` command (⚠️ places real orders)
- **Prometheus metrics** for monitoring and alerting
- **SQLite persistence** for trade history
- **Docker support** with multi-venue deployment
- **Supported exchanges**: Alpaca, Kraken (via CCXT)

See [WARP.md](WARP.md) for comprehensive documentation, architecture details, and development roadmap.

## Quick Start

```bash
# Set up virtual environment
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
python -m pip install -U pip
pip install ccxt pydantic typer prometheus-client orjson websockets pytest

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

💡 **First time?** Use `fitness` command first to verify connectivity. See [WARP.md](WARP.md) for detailed explanations and safety practices.

## Installation

**Requirements:** Python 3.10+ recommended

```bash
# Create and activate virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install ccxt pydantic typer prometheus-client orjson websockets pytest

# Optional: DeFi integration
pip install web3

# Optional: Windows legacy TUI support
pip install windows-curses  # Windows only
```

See [WARP.md Development Workflow](WARP.md#development-workflow) for complete setup instructions.

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
export SQLITE_PATH=./data/arbit.db   # database file path
export PROM_PORT=9109               # metrics server port

# Create data directory
mkdir -p data
```

### Per-Venue Configuration

For multiple exchanges, use venue-specific variables:

```bash
# Alpaca (paper trading recommended)
export ALPACA_API_KEY=your_alpaca_key
export ALPACA_API_SECRET=your_alpaca_secret
export ALPACA_BASE_URL=https://paper-api.alpaca.markets  # Paper trading

# Kraken
export KRAKEN_API_KEY=your_kraken_key
export KRAKEN_API_SECRET=your_kraken_secret
```

### Using .env Files

Copy `.env.example` to `.env` and customize:

```bash
cp .env.example .env
# Edit .env with your credentials
```

See [WARP.md Configuration](WARP.md#configuration-and-environment) for complete variable reference.

## Usage

### Fitness Mode (Read-Only Testing)

Safely test connectivity and monitor spreads without placing orders:

```bash
# Test Kraken connectivity for 20 seconds
python -m arbit.cli fitness --venue kraken --secs 20

# Quick Alpaca test
python -m arbit.cli fitness --venue alpaca --secs 5
```

Typical log line: ``kraken ETH/USDT spread=0.5 bps`` where ``spread`` is the
best ask minus best bid expressed in basis points (1 bps = 0.01%). Smaller
spreads generally indicate deeper liquidity. Use ``--help-verbose`` for more
output guidance.

### Live Trading (⚠️ PLACES REAL ORDERS)

**WARNING**: Only use with tiny amounts and proper risk management!

```bash
# Live trading (runs continuously until stopped)
export PROM_PORT=9109  # Optional: set metrics port
python -m arbit.cli live --venue alpaca

# With different venue
python -m arbit.cli live --venue kraken
```

A typical execution log looks like
``alpaca Triangle(ETH/USDT, ETH/BTC, BTC/USDT) net=0.15% PnL=0.05 USDT``.
Here ``net`` denotes the estimated profit after fees for the triangle and
``PnL`` shows realized profit in USDT. Invoke the command with
``--help-verbose`` to see these explanations from the CLI itself.

### Monitoring & Metrics

Prometheus metrics are exposed on port 9109 by default:

```bash
# View metrics
curl http://localhost:9109/metrics

# Key metrics: orders_total, fills_total, profit_total_usdt
```

**Supported Venues**: `alpaca`, `kraken`

**Note**: Ensure triangle symbols exist on your chosen venue (ETH/USDT, ETH/BTC, BTC/USDT). See [WARP.md CLI Commands](WARP.md#cli-commands) for full documentation.

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

**⚠️ EXTREME CAUTION**: Never use mainnet private keys in development. See [WARP.md DeFi Integration](WARP.md#defi-integration) for safety practices.

## Troubleshooting

**Common Issues:**

- **Credentials**: Ensure `ARBIT_API_KEY`/`ARBIT_API_SECRET` match your `--venue`
- **Symbols**: Verify triangle legs exist (some venues use `ETH/BTC` vs `BTC/ETH`)
- **Rate limits**: Reduce polling frequency if getting rate limited
- **Data directory**: Run `mkdir -p data` or set `SQLITE_PATH` to custom location
- **Metrics**: Check port availability and Docker port mapping
- **Dependencies**: Ensure all packages installed in active venv

See [WARP.md Troubleshooting](WARP.md#common-issues-and-troubleshooting) for detailed solutions.

## FAQ

**Q: Does this place actual trades?**
A: `fitness` is read-only. `live` **WILL place real orders** if keys have trading permissions.

**Q: Which exchanges are supported?**  
A: Currently Alpaca and Kraken via CCXT. More exchanges can be added.

**Q: How accurate are profit estimates?**
A: Estimates assume perfect execution at top-of-book prices. Real trading involves slippage, fees, and partial fills.

**Q: Do I need API keys?**
A: Yes, even for `fitness` mode to access order book data.

**Q: Is this ready for production?**
A: **NO**. This is development/research software. See [safety warnings](#%EF%B8%8F-important-safety-notice) above.

## For Developers

This README provides user-focused documentation. For comprehensive technical details:

- **[WARP.md](WARP.md)** - Complete documentation (architecture, roadmap, development)
- **Tests**: `pytest -q` 
- **Deprecated legacy TUI**: `python deprecated/legacy_arbit.py --tui` (use `python -m arbit.cli` instead)

## Acknowledgments

Built with [CCXT](https://github.com/ccxt/ccxt) for exchange connectivity, [Pydantic](https://pydantic-docs.helpmanual.io/) for configuration, and [Typer](https://typer.tiangolo.com/) for CLI interface.

---

📖 **Complete Documentation**: [WARP.md](WARP.md)  
⚠️ **Safety First**: Always test with paper trading and minimal amounts
