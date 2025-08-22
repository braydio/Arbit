Goal: A money farming bot with minimal babysitting, start with:

Phase 1 (weekend MVP):

Implement the single‑exchange triangle with ccxt, REST polling first, tiny notionals, full logging, no real orders for a few hours → flip to live with strict max notional and IOC orders.

Side‑task: deploy the Aave depositor (that’s a one‑time supply + a dashboard metric).

Phase 2:

Move arb to WebSockets / connectors, add multi‑symbol rotation, inventory rebalancing, Prometheus.

Add stablecoin auto‑allocator logic with thresholded moves.
