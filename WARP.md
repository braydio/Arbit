# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

# Arbit Triangular Arbitrage Monitor

This repository contains a triangular arbitrage monitoring system for cryptocurrency exchanges, designed to evolve from a simple MVP monitor to a full-featured automated trading system.

## TLDR Quickstart

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
python -m pip install -U pip
pip install ccxt

python arbit.py --help
python arbit.py --cycles 5
python arbit.py --tui
python arbit.py --exchange kraken --tui
```

**Notes:**
- API keys are optional for public order books. The MVP does not place orders.
- Use a terminal that supports curses for the TUI.

## Development Workflow

### Virtual Environment
```bash
python -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install ccxt
```

### Run Modes
- Headless sampler: `python arbit.py --cycles 25`
- Live TUI: `python arbit.py --tui`
- Different exchange: `python arbit.py --exchange kraken --tui`
- Help: `python arbit.py --help`

### Adjust MVP Constants (in arbit.py)
- `EX`: default exchange id string (default: "kraken")
- `SYM_AB`, `SYM_BC`, `SYM_AC`: symbols for the triangle (default: ETH/USDT, ETH/BTC, BTC/USDT)
- `FEE`: taker fee decimal (default: 0.001)
- `THRESH`: net threshold decimal (default: 0.001)
- `QTY_USDT`: per-cycle notional cap for informational estimate (default: 200)

### Output Formats
- TUI shows top-of-book bid/ask for each market plus net estimate
- Headless prints one line per loop iteration

### Platform-Specific Notes
- Windows TUI dependency: `pip install windows-curses`
- Deactivate venv: `deactivate`

## Configuration and Environment

### MVP (arbit.py)
Optional environment variables for private endpoints:
```bash
export API_KEY=your_key_if_needed
export API_SECRET=your_secret_if_needed
```

- Default exchange: kraken. Override with `--exchange`
- Ensure symbols exist on your chosen exchange or edit `SYM_*` constants
- Python 3.10+ recommended, 3.11+ ideal

### Future Configuration (Planned)
Based on ROADMAP.md, the system will support:
- `.env` file with entries like `KRAKEN_API_KEY`, `KRAKEN_API_SECRET`, `NET_THRESHOLD_BPS`, `DRY_RUN`, `PROM_PORT`, `SQLITE_PATH`, `DISCORD_WEBHOOK_URL`
- Exchange-specific keys uppercased by ccxt id
- Additional dependencies: websockets, pydantic, typer, prometheus-client, orjson, sqlite

## What Ships Today (MVP)

**Core Functionality:**
- Single-exchange monitor for USDT → ETH → BTC → USDT triangular cycle
- REST polling using ccxt `fetch_order_book` for ETH/USDT, ETH/BTC, BTC/USDT
- Curses-based TUI and headless console output modes
- **NO LIVE ORDERS** - monitor only, read-only operation

**Performance:**
- 50ms sleep between polling cycles
- Rate limiting enabled at ccxt client level
- Displays estimated profit opportunities when net return exceeds threshold

## Strategy and Math

### Triangular Arbitrage Cycle
USDT → ETH → BTC → USDT via symbols:
- AB = ETH/USDT (buy ETH with USDT)
- BC = ETH/BTC (sell ETH for BTC)
- AC = BTC/USDT (sell BTC for USDT)

### Profit Calculation
```text
gross = (1 / ask_AB) * bid_BC * bid_AC
net   = gross * (1 - fee)^3 - 1
```

**Key Parameters:**
- `FEE` default: 0.001 (10 basis points per leg). Replace with venue-accurate taker fee for production.
- `THRESH` default: 0.001 (10 basis points minimum net return)
- Notional estimate: Based on first leg depth with `QTY_USDT` cap

**Important:** Real execution requires IOC market orders, slippage headroom, and depth-aware sizing across all legs. The MVP provides estimates only.

## Architecture: Today vs Planned

### Current State (MVP)
- Single file `arbit.py` containing all logic
- REST polling loop with `compute_net` function
- Simple curses TUI for visualization
- No order execution or simulation

### Planned Architecture (per ROADMAP.md)

**Configuration Layer:**
- Pydantic Settings with .env support
- Exchange-specific API key management

**Data Models:**
- `Triangle`: symbol configuration
- `OrderSpec`: order specifications  
- `Fill`: execution results

**Exchange Adapters:**
- `ExchangeAdapter` ABC with standardized interface
- `CcxtAdapter` implementation for multiple venues
- Optional native WebSocket implementations for speed

**Execution Engine:**
- Triangle math and opportunity detection
- Depth-aware position sizing
- Three-leg IOC order executor with atomicity
- Risk controls: min notional, slippage caps, inventory limits
- Idempotent client IDs and kill switches

**Infrastructure:**
- SQLite persistence for trades and cycles
- Prometheus metrics exporter
- Typer-based CLI with fitness and live commands
- Docker containerization with docker-compose
- Discord webhook alerting

**DeFi Integration:**
- Aave USDC allocator as separate module
- Automated stablecoin yield optimization

## Development Roadmap

### Phase 1 (MVP Weekend)
- ✅ ccxt REST monitor with TUI
- ✅ Single triangle, single exchange
- ✅ Estimates only, no execution
- 🔄 Optional: Aave USDC deposit utility

### Phase 2 (Production Ready)
- WebSocket order books for reduced latency
- Multi-symbol rotation and inventory rebalancing  
- Prometheus metrics and monitoring
- Dry-run execution mode → controlled live trading
- Strict notional caps and IOC-only orders
- Automated stablecoin allocator with thresholds

### Phase 3 (Multi-Exchange)
- Cross-exchange arbitrage routing
- Hedger logic for risk management
- Robust error handling and recovery
- Idempotent operations with client IDs
- Production alerting and monitoring
- Full containerization and deployment automation

## Safety and Risk Management

### Current Safety (MVP)
- **Read-only operation** - no orders placed
- All outputs are estimates only
- Rate limiting enabled to respect exchange limits

### Planned Safety Features
- Default to `DRY_RUN=true` for all execution
- Start with tiny notionals (e.g., $10) for initial live testing
- IOC (Immediate or Cancel) orders only to avoid getting stuck
- Strict net threshold enforcement
- Maximum slippage and position size limits
- Inventory caps per asset
- Kill switches for volatility or connectivity issues

## Common Issues and Troubleshooting

### Exchange/Symbol Issues
- **Symbol not found**: Ensure chosen exchange supports ETH/USDT, ETH/BTC, BTC/USDT or edit `SYM_*` constants
- **Exchange errors**: Verify exchange name matches ccxt id (e.g., "kraken", "binance")

### Technical Issues  
- **Curses on Windows**: Install `windows-curses` package
- **Rate limits**: Keep `enableRateLimit=True` in ccxt and increase sleep intervals if needed
- **Terminal encoding**: Ensure UTF-8 support for proper character display

### Debugging
- Use headless mode with small cycle count: `python arbit.py --cycles 10`
- Add temporary print statements around `compute_net` inputs
- Reduce sleep duration to observe rapid behavior changes

## FAQ

**Q: Does this place actual trades?**
A: No, the current MVP is monitor-only. It displays profit estimates but never places orders.

**Q: Do I need API keys?**
A: Not for the MVP. Keys are only needed when adding private endpoint functionality (balance checks, order placement).

**Q: Which exchange is used by default?**
A: Kraken. Override with `--exchange <exchange_name>` where exchange_name is a valid ccxt exchange id.

**Q: How accurate are the profit estimates?**
A: Estimates assume perfect execution at top-of-book prices with uniform fees. Real trading involves slippage, partial fills, and varying fees per market.

## Key Files Reference

- **`arbit.py`**: Main MVP implementation with TUI and console modes
- **`README.md`**: Basic usage instructions and cycle explanation  
- **`ROADMAP.md`**: Detailed future architecture and implementation plans
- **`profit-calc`**: Mathematical formula reference for net profit calculation
- **`stake.py`**: Prototype Aave integration for DeFi yield farming

## Common Development Commands

```bash
# Quick test run
python arbit.py --cycles 5

# Monitor with TUI
python arbit.py --tui

# Test different exchange
python arbit.py --exchange binance --cycles 10

# Check available exchanges
python -c "import ccxt; print([ex for ex in sorted(ccxt.exchanges)[:10]])"

# Environment setup from scratch
rm -rf .venv && python -m venv .venv && source .venv/bin/activate && pip install ccxt
```
