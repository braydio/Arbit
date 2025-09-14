# ROADMAP

This document outlines current capabilities and future development for the Arbit triangular arbitrage system.


For installation and configuration guidance, see the [README](README.md).

## What Ships Today

**Core Functionality:**
- Modular Python package with Typer CLI interface
- Native Alpaca REST/websocket via `AlpacaAdapter` (alpaca-py) and CCXT order books through `CCXTAdapter`
- Simplified execution via three limit orders at top-of-book prices when threshold exceeded
- Prometheus metrics (orders_total, fills_total, profit_total)
- SQLite persistence (triangles, fills tables)
- Supported exchanges: `alpaca` (native), `kraken` (via CCXT)

**CLI Modes:**
- `fitness`: Read-only connectivity/spread sampling
- `live`: Simplified live attempts; places orders if keys have trade permissions

**Performance:**
- Loops at ~1s cadence in CLI examples; Kraken path rate-limited via CCXT
- Docker containerization with docker-compose for multi-venue deployment

## Strategy and Math

### Triangular Arbitrage Cycle
USDT → ETH → BTC → USDT via symbols:
- AB = ETH/USDT (buy ETH with USDT)
- BC = ETH/BTC (sell ETH for BTC)
- AC = BTC/USDT (sell BTC for USDT)

Additional default candidate:
- USDT → SOL → BTC → USDT via `SOL/USDT`, `SOL/BTC`, `BTC/USDT`.
  Rationale: high liquidity and active BTC cross tend to create frequent small dislocations. Validate symbol availability per venue with `keys:check`.

### Profit Calculation
**Current Implementation:**
```text
net = (1 / ask_AB) * bid_BC * bid_AC - 1
```

**Legacy Formula (with fees):**
```text
gross = (1 / ask_AB) * bid_BC * bid_AC
net   = gross * (1 - fee)^3 - 1
```

**Key Notes:**
- The current engine's `net_edge_cycle` multiplies supplied edges and subtracts one
- Fees are not explicitly modeled in the current implementation by default
- Sizing uses `size_from_depth` with the minimum size across top levels of each leg
- **Important:** Slippage, fees, and partial fills are not yet accounted for - consider these before live trading

## Architecture: Current Implementation

### Modular Package Structure
**Configuration:**
- `arbit/config.py` (Pydantic Settings, env prefix ARBIT_)

**Alpaca Settings:**
- `ALPACA_BASE_URL` to select paper or live API endpoint
- `ALPACA_WS_CRYPTO_URL` to override websocket endpoint
- `ALPACA_MAP_USDT_TO_USD` to treat `/USDT` symbols as `/USD`

**Models:**
- `arbit/models.py` (Triangle, OrderSpec, Fill)

**Exchange Adapters:**
- `arbit/adapters/base.py` (ExchangeAdapter ABC)
- `arbit/adapters/alpaca_adapter.py` (native Alpaca API via alpaca-py)
- `arbit/adapters/ccxt_adapter.py` (CCXT-backed adapter for Kraken and others)

**Engine:**
- `arbit/engine/triangle.py` (top-of-book helpers, net_edge_cycle, size_from_depth)
- `arbit/engine/executor.py` (try_triangle orchestration)

**Persistence:**
- `arbit/persistence/db.py` (SQLite schema + insert helpers)

**Metrics:**
- `arbit/metrics/exporter.py` (Prometheus counters/gauges and server start)

**CLI:**
- `arbit/cli.py` (Typer interface: fitness, live)

**DeFi:**
- `stake.py` (Aave v3 supply demo)

### Future Enhancements (per ROADMAP.md)

**Configuration Layer:**
- Pydantic Settings with .env support
- Exchange-specific API key management

**Data Models:**
- `Triangle`: symbol configuration
- `OrderSpec`: order specifications  
- `Fill`: execution results

**Exchange Adapters:**
- `ExchangeAdapter` ABC with standardized interface
- `CCXTAdapter` implementation for multiple venues
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

- [x] ccxt REST monitor with TUI
- [x] Single triangle, single exchange
- [x] Estimates only, no execution
- [ ] Optional Aave USDC deposit utility

### Phase 2 (Production Ready)
- [ ] WebSocket order books for reduced latency
- [ ] Multi-symbol rotation and inventory rebalancing
- [ ] Prometheus metrics and monitoring
- [ ] Dry-run execution mode → controlled live trading
- [ ] Strict notional caps and IOC-only orders
- [ ] Automated stablecoin allocator with thresholds

### Phase 3 (Multi-Exchange)
- [ ] Cross-exchange arbitrage routing
- [ ] Hedger logic for risk management
- [ ] Robust error handling and recovery
- [ ] Idempotent operations with client IDs
- [ ] Production alerting and monitoring
- [ ] Full containerization and deployment automation

## Safety and Risk Management

### Current Safety Features
- `fitness` command is read-only and safe for connectivity testing; add `--simulate` to try dry-run executions
- `live` command can place real orders
- No IOC/time-in-force or slippage rails implemented by default
- Top-of-book limit orders are used
- Rate limiting enabled to respect exchange limits

### Recommended Safety Practices
- Start with tiny notionals and short cycles for initial testing
- Use venue sandbox or paper trading environments if available
- Monitor metrics and logs carefully
- Set net threshold conservatively
- Ensure data directory exists: `mkdir -p data`

### Planned Safety Features
- Explicit dry-run mode toggle
- IOC (Immediate or Cancel) orders to avoid getting stuck
- Strict notional caps and slippage limits
- Inventory caps per asset
- Kill switches for volatility or connectivity issues

## Common Issues and Troubleshooting

### Credentials
- Ensure `ARBIT_API_KEY`/`ARBIT_API_SECRET` are set for the selected `--venue`
- With docker-compose, supply venue-specific keys in `.env` and compose maps them

### Symbols
- Verify triangle legs exist on the chosen venue (e.g., ETH/USDT, BTC/ETH, BTC/USDT)

### Alpaca Settings
- `ALPACA_BASE_URL` controls paper vs live REST endpoint
- `ALPACA_WS_CRYPTO_URL` overrides websocket stream
- Enable `ALPACA_MAP_USDT_TO_USD` to map `/USDT` pairs to `/USD`

### CCXT Errors (Kraken)
- Keep `enableRateLimit=True`; reduce polling frequency if rate-limited

### Metrics
- Confirm `--metrics-port` matches exposed port; use `curl` to verify

### SQLite
- Data path defaults to `./data`; ensure directory exists or set `ARBIT_DATA_DIR`


## FAQ

**Q: Does this place actual trades?**
A: The `fitness` command is read-only. The `live` command can place real orders if API keys have trading permissions.

**Q: Do I need API keys?**
A: Yes, for both `fitness` and `live` commands. Keys are required for order book access.

**Q: Which exchanges are supported?**
A: Currently `alpaca` (native API) and `kraken` via the CCXT adapter.

**Q: How accurate are the profit estimates?**
A: Estimates assume perfect execution at top-of-book prices. Real trading involves slippage, partial fills, and fees.

## Key Files Reference

- **CLI**: `arbit/cli.py`
- **Config**: `arbit/config.py`
- **Models**: `arbit/models.py`
- **Adapters**: `arbit/adapters/base.py`, `arbit/adapters/alpaca_adapter.py`, `arbit/adapters/ccxt_adapter.py`
- **Engine**: `arbit/engine/triangle.py`, `arbit/engine/executor.py`
- **Persistence**: `arbit/persistence/db.py`
- **Metrics**: `arbit/metrics/exporter.py`
- **DeFi**: `stake.py`
- **Docker**: `Dockerfile`, `docker-compose.yml`
- **Tests**: `tests/test_triangle.py`

## Common Development Commands

```bash
# Quick connectivity test
python -m arbit.cli fitness --venue kraken --secs 5
python -m arbit.cli fitness --venue alpaca --secs 5 --simulate --persist

# Live (caution: may place orders)
python -m arbit.cli live --venue alpaca --cycles 1 --metrics-port 9109

# Run unit tests
pytest -q

# Check available exchanges in ccxt
python -c "import ccxt; print(sorted(ccxt.exchanges)[:10])"

# Clean venv and reinstall deps
rm -rf .venv && python -m venv .venv && source .venv/bin/activate && pip install -U pip && pip install alpaca-py ccxt pydantic typer prometheus-client orjson websockets pytest web3

# Docker up both venues
docker compose up -d --build
```
