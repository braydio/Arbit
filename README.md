Goal: A money farming bot with minimal babysitting, start with:

Phase 1 (weekend MVP):

Implement the single‑exchange triangle with ccxt, REST polling first, tiny notionals, full logging, no real orders for a few hours → flip to live with strict max notional and IOC orders.

Side‑task: deploy the Aave depositor (that’s a one‑time supply + a dashboard metric).

Phase 2:

Move arb to WebSockets / connectors, add multi‑symbol rotation, inventory rebalancing, Prometheus.

Add stablecoin auto‑allocator logic with thresholded moves.

## Usage

The `legacy_arbit.py` script now exposes a small curses based TUI for monitoring
triangular arbitrage opportunities on a single exchange.  Install
dependencies (`pip install ccxt`) and run:

```bash
python legacy_arbit.py --tui
```

To run a finite number of iterations without the UI for testing or
scripting, use the `--cycles` flag:

```bash
python legacy_arbit.py --cycles 5
```

The script fetches order books for `ETH/USDT`, `BTC/ETH` and `BTC/USDT`
and prints the estimated net return of the USDT→ETH→BTC→USDT cycle.

### Typer CLI

A Typer-based interface exposes `fitness` and `live` commands:

```bash
python -m arbit.cli fitness --venue alpaca --secs 5
python -m arbit.cli live --venue alpaca --cycles 1
```

Both commands load credentials from environment variables (`ARBIT_API_KEY`,
`ARBIT_API_SECRET`) and use them to connect via `ccxt`.
