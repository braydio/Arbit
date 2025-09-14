# Phase II — Production-Ready Roadmap

This document expands Phase II into concrete, testable deliverables needed to run Arbit reliably in production-like environments.

## Scope & Goals
- Reduce latency and improve data quality with WebSocket order books.
- Safely execute multi-leg arbitrage with strict risk controls and robust recovery.
- Operate across multiple symbols with inventory awareness and rebalancing.
- Provide first-class observability, persistence, and documentation for safe operations.

## High-Level Deliverables
- Exchange data via WebSockets with REST fallback and staleness guards.
- Depth-aware execution with IOC and per-leg safety rails; idempotent client IDs.
- Multi-symbol rotation and inventory rebalancing across configured triangles.
- Prometheus metrics with dashboards and alerting; structured logs.
- SQLite persistence with migrations and auditable records of ops and snapshots.
- Typer CLI enhancements and comprehensive tests; Dockerized deployment path.

## Workstreams and Acceptance Criteria

### 1) Market Data (WebSockets)
- Implement order book streaming per venue (Kraken via CCXT, Alpaca via native adapter).
- Maintain in-memory top-of-book with incremental updates; verify sequence integrity.
- Fallback to REST when streams are stale; emit metric for staleness events.
- Configurable `max_book_age_ms` with default sane values per venue.
- Acceptance:
  - 99% of cycles use WS-derived quotes; median staleness < 250 ms.
  - `market_data_staleness_ms` histogram available; alerts on >2s for 1m.

Progress
- [x] Stream API surface in adapter (`orderbook_stream`) with REST fallback.
- [ ] Initialize `ccxt.pro` client (`ex_ws`) when present; per-symbol watch with retries.
- [ ] Add `orderbook_staleness_seconds` histogram; measure inter-update deltas.
- [ ] Tests with fake stream to validate staleness and fallback behavior.

### 2) Execution Engine Hardening
- Place IOC limit orders for all legs; enforce per-leg `max_slippage_bps` and `min_notional`.
- Idempotent client order IDs and retry policy with exponential backoff and jitter.
- Partial fill handling: detect fills, cancel remainders, compute remaining inventory deltas.
- Failure atomicity: if leg N fails, cancel outstanding legs and record incident.
- Fees explicitly modeled per venue; include in edge and sizing.
- Acceptance:
  - All orders carry client IDs; duplicate-submission safe.
  - Unit tests for partial fills, cancellation flow, and retry backoff.
  - Profit calc includes fees; slippage guard rejects orders beyond cap.

### 3) Strategy: Multi-Symbol Rotation & Inventory
- Configure multiple triangles per venue (ETH/BTC/USDT, SOL/BTC/USDT, ...).
- Rotation policy: prioritize latest net edge and liquidity; avoid thrashing via cool-down.
- Inventory tracking: maintain per-asset inventory, respect caps, and rebalance opportunistically.
- Acceptance:
  - Rotation exercised in simulation; inventory never exceeds configured caps.
  - Persisted snapshots reflect inventory changes after partials and rebalances.

### 4) Risk Controls & Kill Switches
- Global kill switch via env/flag; per-venue pause.
- Circuit breaker: pause venue on repeated failures/timeouts within window.
- Enforce `MAX_CONCURRENT_CYCLES`, `MAX_NOTIONAL_PER_CYCLE`, and per-asset caps.
- Acceptance:
  - Circuit breaker test triggers pause and emits alert event/metric.
  - Notional/asset caps enforced in unit tests and simulation.

### 5) Metrics & Observability
- Prometheus: counters (orders, fills, rejects), histograms (latency, staleness), gauges (inventory, PnL).
- Structured logs (JSON) for orders, fills, cancellations, and errors (no secrets).
- Optional Discord/webhook alerts for circuit breaks and severe errors.
- Acceptance:
  - `curl /metrics` exposes the new series; example Grafana dashboard JSON in `docs/`.
  - Log samples and field dictionary added to README/WARP.

### 6) Persistence & Migrations
- Versioned schema with lightweight migrations; include triangles, fills, incidents, snapshots.
- Periodic snapshots: wallet + aToken balances (if configured) and venue inventories.
- Acceptance:
  - Migration script upgrades existing DB without data loss.
  - Tests cover insert/read of all new tables and snapshot cadence.

### 7) Configuration Layer
- Pydantic Settings: per-venue fees, min notionals, ws enable, thresholds.
- Sensible defaults and `.env` examples; secrets never logged.
- Acceptance:
  - Validation errors for invalid configs; typed settings in `arbit/config.py`.

### 8) CLI & UX
- `fitness` supports `--simulate`, WS toggles, metrics port.
- `live` supports IOC-only execution, notional/slippage flags, `--dry-run` global guard.
- `keys:check` validates symbols and shows venue-specific limits and fees.
- Acceptance:
  - `typer.testing.CliRunner` tests cover flags and help text.

### 9) Testing & QA
- Unit tests for triangle math, sizing, fees/slippage, and engine flows.
- Integration tests with mocked adapters (no real APIs).
- Property tests for reserve math and edge cases.
- Soak-style simulation for rotation, inventory, and circuit breaker.
- Acceptance:
  - `pytest -q` green; coverage threshold >= 80% on changed areas.

### 10) CI/CD & Packaging
- Lint (Ruff), format (Black), type-check (mypy/pyright optional), tests on CI.
- Docker image(s) include WS deps and run non-root; sample compose for multi-venue.
- Acceptance:
  - CI pipeline badge; container builds and runs `fitness` in compose example.

### 11) Documentation & Runbooks
- Expand README/WARP with safety checklist, WS notes, flags, and examples.
- Operator runbook: start/stop, kill switch, troubleshooting, and metrics guide.
- Acceptance:
  - Docs include copy-paste examples; screenshots/log snippets where helpful.

## Milestones
1. WS data layer with REST fallback and metrics.
2. Execution IOC + risk rails + fees modeling.
3. Multi-symbol rotation and inventory tracking.
4. Observability pass (metrics/logs) and persistence snapshots.
5. Test hardening, docs, and Docker examples.

## Rollout Plan
- Start in `fitness --simulate` with WS enabled; verify metrics and staleness.
- Enable `live --dry-run` to validate sizing and guards.
- Small-notional live trials on a single venue with circuit breaker on.
- Gradual symbol enablement with inventory caps; monitor dashboards.

## Out of Scope
- Cross-exchange routing and hedger (Phase 3).
- DeFi allocation/rotation beyond basic provider plumbing.

---
For current status and Phase I notes, see `ROADMAP.md`.
