# ROADMAP

This document outlines current capabilities and future plans for the Arbit triangular arbitrage system.

For installation and configuration guidance, see [README](../README.md) or [WARP.md](WARP.md).

## What Ships Today

**Core Functionality:**
- Modular Python package with Typer CLI interface
- CCXT REST order books and order placement through `CCXTAdapter`
- Simplified execution via three limit orders at top-of-book prices when threshold exceeded
- Prometheus metrics (orders_total, fills_total, profit_total)
- SQLite persistence (triangles, fills tables)
- Supported exchanges: `alpaca` (native), `kraken` (CCXT)

**CLI Modes:**
- `fitness`: Read-only connectivity/spread sampling; optional dry-run simulation (`--simulate`)
- `live`: Simplified live attempts; places orders if keys have trade permissions

**Performance:**
- Loops at ~1s cadence in CLI examples; rate-limited at CCXT level
- Docker containerization with docker-compose for multi-venue deployment

## Strategy and Math

### Triangular Arbitrage Cycle
USDT → ETH → BTC → USDT via symbols:
- AB = ETH/USDT (buy ETH with USDT)
- BC = ETH/BTC (sell ETH for BTC)
- AC = BTC/USDT (sell BTC for USDT)

### New Triangle Candidate: SOL → BTC → USDT
- AB = SOL/USDT (buy SOL with USDT)
- BC = SOL/BTC (sell SOL for BTC)
- AC = BTC/USDT (sell BTC for USDT)

Rationale: SOL has strong liquidity and an active BTC cross on Alpaca and Kraken, increasing the odds of small, frequent inefficiencies. This triangle is added to default configs for both venues. Rollout steps below help validate safely.

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
- **Important:** Slippage, fees, and partial fills are not yet fully accounted for - consider these before live trading

## Architecture: Current Implementation

### Modular Package Structure
**Configuration:**
- `arbit/config.py` (Pydantic Settings, env prefix ARBIT_)

**Models:**
- `arbit/models.py` (Triangle, OrderSpec, Fill)

**Exchange Adapters:**
- `arbit/adapters/base.py` (ExchangeAdapter ABC)
- `arbit/adapters/alpaca_adapter.py` (native Alpaca API)
- `arbit/adapters/ccxt_adapter.py` (CCXT-backed adapter for kraken)

**Engine:**
- `arbit/engine/triangle.py` (top-of-book helpers, net_edge_cycle, size_from_depth)
- `arbit/engine/executor.py` (try_triangle orchestration)

**Persistence:**
- `arbit/persistence/db.py` (SQLite schema + insert helpers)

**Metrics:**
- `arbit/metrics/exporter.py` (Prometheus counters/gauges and server start)

**CLI:**
- `arbit/cli/` (Typer interface: fitness, live)

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

### Phase 1 (MVP Weekend) — Status
 - [x] CCXT REST monitor — Complete
 - [x] Single triangle, single exchange — Complete
 - [x] Estimates only, no execution — Complete (initial MVP; now superseded by basic executor listed in "What Ships Today")
 - [ ] Optional: Aave USDC deposit utility — Pending

#### Hardening/Improvements (post‑MVP)
- Execution safety: enforce IOC/timeouts, explicit dry‑run, and strict notional/slippage caps.
- Fees/slippage modeling: include taker fees and spread impact in `net_edge_cycle` and sizing.
- Partial fills handling: detect partials, cancel remainders, and reconcile inventory.
- Resilience: idempotent client IDs, retries with backoff, circuit breakers on repeated failures.
- Observability: enrich Prometheus metrics (latency histograms, error counters) and structured logs.
- Persistence: add schema migrations and more frequent snapshots for auditability.
- Docs: expand safety checklist and examples for paper/live flows; clarify venue quirks.

### Phase 2 (Production Ready)
 - [ ] WebSocket order books for reduced latency
   - [x] CLI scaffolding and adapter method (`orderbook_stream`)
   - [ ] Initialize `ccxt.pro` client when available (`ex_ws`)
   - [ ] Fallback to REST with staleness guard and metrics
   - [ ] Basic tests with mocked stream/polling
 - [x] Multi-venue live mode (concurrent)
   - [x] `live:multi` command with per-venue loops
   - [x] Discord notifications include balances per venue
 - [ ] Multi-symbol rotation and inventory rebalancing
 - [ ] Prometheus metrics and monitoring
   - [ ] Order book staleness histogram
   - [ ] Error counters for WS connect/retry

See `ROADMAP_PHASE_II.md` for detailed Phase II deliverables, acceptance criteria, and test plan.

### Triangle Expansion (Ongoing)
- [x] Add SOL/USDT–SOL/BTC–BTC/USDT to default triangles (alpaca, kraken)
- [ ] Verify symbol availability per venue with `keys:check` in docs/examples
- [ ] Paper test in `fitness --simulate` and persist to SQLite for sizing review
- [ ] Tune `NET_THRESHOLD_BPS` and `MAX_SLIPPAGE_BPS` per venue for SOL triangle
- [ ] Monitor `min_notional` and taker fees per leg; document venue-specific quirks
- [ ] Consider adding XRP/BTC/USDT as a next candidate pending liquidity checks
 - [ ] Dry-run execution mode for controlled live trading
 - [ ] Strict notional caps and IOC-only orders
 - [ ] Automated stablecoin allocator with thresholds

### Phase 3 (Multi-Exchange)
 - [ ] Cross-exchange arbitrage routing
 - [ ] Hedger logic for risk management
 - [ ] Robust error handling and recovery
 - [ ] Idempotent operations with client IDs
 - [ ] Production alerting and monitoring
- [ ] Full containerization and deployment automation

## Yield (DeFi) Readiness Roadmap

This section tracks what remains to make yield commands robust for dev/live testing.

### Dependencies & Packaging
- [ ] Unify dependency versions (root vs `arbit/requirements.txt`) for `pydantic`, `typer`, `prometheus-client`.
- [x] Add `web3` runtime dependency for yield features.
- [ ] Ensure Docker images include `web3` and required build deps.

### Configuration & Settings
- [ ] Chain config abstraction: network selection (`ARBIT_CHAIN=arbitrum|mainnet|...`), per-chain `usdc_address`, `pool_address`, decimals.
- [ ] Safer defaults: `DRY_RUN=true`, conservative `max_gas_price_gwei`, `reserve_amount_usd`.
- [ ] Optional: provider selector for yield (`AAVE`, `...`), and `YIELD_SOURCES` default for watch.
- [ ] Secrets handling: document `.env` keys; ensure PRIVATE_KEY never logs.

### Modules & Abstractions
- [x] Provider interface for yield (`arbit/yield/providers.py`) with AaveProvider wrapper.
- [ ] APR source clients with schema validation, retries, and jitter backoff.
- [x] Wallet accounting hook to read aToken balance when `atoken_address` is configured.
- [ ] Gas strategy (EIP-1559) and chain-specific fee modeling.

### CLI Commands
- [x] `yield:collect` basic USDC deposit with reserves and dry-run (now via provider).
- [x] `yield:watch` APR polling with metrics and Discord alerts.
- [x] `yield:withdraw` targeted withdrawals and `--all-excess` top-up logic; uses aToken balance if configured.
- [ ] Add `--provider` flag and support multiple providers; surface chain/asset decimals.
- [ ] Add `yield:rebalance` to move between providers when `yield:watch` signals improvement.
- [ ] Robust argument validation and `--help-verbose` examples for all yield commands.

### Safety & Risk Controls
- [ ] End-to-end dry-run simulation for on-chain txs with printed calldata and gas estimates.
- [ ] Inventory limits and per-tx caps; enforce `min_usdc_stake` everywhere.
- [ ] Error taxonomy with retries/backoff and circuit breakers for repeated failures.
- [ ] Explicit kill switch via env/flag to pause on-chain operations.

### Metrics & Observability
- [x] Start Prometheus server in `yield:watch`.
- [ ] Set `YIELD_CAPITAL_USD` based on wallet + aToken balances after ops.
- [ ] Structured logging for tx hashes, nonces, and provider decisions (without secrets).
- [ ] Optional Discord heartbeat and summarised daily reports.

### Persistence
- [x] Add `yield_ops` table (timestamp, provider, op, amount, tx_hash, mode, error) for auditable history.
- [ ] Snapshot APR observations to SQLite for backtesting alert thresholds and realized yield.

### Testing
- [x] Unit tests for provider balance reads with injected dummy web3.
- [x] Unit tests for `yield:collect` and `yield:withdraw` dry-run flows with mocked provider/web3.
- [ ] Tests for `yield:watch` with local JSON/CSV and alert threshold logic.
- [ ] Property tests for reserve math and min-stake edge cases.
- [ ] Lint/type checks for new modules.

### Documentation
- [ ] Expand README/WARP with chain setup, safety checklist, and provider details.
- [ ] Provide sample APR files and schemas; examples for Docker usage with RPC URLs.

### Stretch
- [ ] Support permit (EIP-2612) flow to skip explicit `approve` when possible.
- [ ] Multi-asset support beyond USDC (USDT/DAI) with decimal awareness.
- [ ] Strategy to auto-rotate capital across providers based on moving average APRs.

## What Still Needs Implementation (Yield Farming)

### Persistence + Tracking
- [x] Create `yield_ops` table in `arbit/persistence/db.py` and write records for deposit/withdraw actions and errors.
- [ ] Add periodic snapshot of wallet + aToken balances and APR observations for history and reporting.

### Yield / APY Calculation
- [ ] Query aToken balances periodically and compute realized yield vs principal.
- [ ] Add reporting loop (CLI or background task) to persist yield over time.

### Strategy Layer
- [ ] Allocation strategy to determine capital split between arbitrage and yield based on thresholds.
- [ ] Auto-compound: periodic withdraw/redeposit of accrued rewards if thresholds met.

### Testing / Dev Mode
- [ ] Add yield CLI tests under `tests/` using mocked provider or eth-tester.
- [ ] Optional: local chain integration (eth-tester/Ganache) for end-to-end dry-run.

### RPC and APIs
- [ ] RPC endpoint (HTTPS/WSS) set via `RPC_URL` for web3.py.
- [ ] Aave v3 Pool and ERC20 ABIs/addresses (present) + optional aToken address via settings.
- [ ] (Optional) Price feed (Chainlink/CEX/Uniswap) to value balances in USD.

## Safety and Risk Management

### Current Safety Features
- `fitness` command is read-only and safe for connectivity testing; use `--simulate` to dry-run
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

### CCXT Errors
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
A: Currently `alpaca` via a native adapter and `kraken` through CCXT.

**Q: How accurate are the profit estimates?**
A: Estimates assume perfect execution at top-of-book prices. Real trading involves slippage, partial fills, and fees.

## Key Files Reference

- **CLI**: `arbit/cli/`
- **Config**: `arbit/config.py`
- **Models**: `arbit/models.py`
- **Adapters**: `arbit/adapters/base.py`, `arbit/adapters/alpaca_adapter.py`, `arbit/adapters/ccxt_adapter.py`
- **Engine**: `arbit/engine/triangle.py`, `arbit/engine/executor.py`
- **Persistence**: `arbit/persistence/db.py`
- **Metrics**: `arbit/metrics/exporter.py`
- **DeFi**: `stake.py`
- **Docker**: `Dockerfile`, `docker-compose.yml`
- **Tests**: `tests/test_triangle.py`
