"""Market inspection CLI commands."""

from __future__ import annotations

from arbit.config import settings

from ..core import app, log
from ..utils import _build_adapter, _triangles_for


@app.command("markets:limits")
@app.command("markets_limits")
def markets_limits(venue: str = "alpaca", symbols: str | None = None) -> None:
    """List min-notional and maker/taker fees for symbols."""

    adapter = _build_adapter(venue, settings)
    try:
        markets = adapter.load_markets()
    except Exception:
        markets = {}

    if symbols:
        selected = [sym.strip() for sym in symbols.split(",") if sym.strip()]
    else:
        tris = _triangles_for(venue)
        selected = sorted(
            {s for tri in tris for s in (tri.leg_ab, tri.leg_bc, tri.leg_ac)}
        )

    for symbol in selected:
        if markets and symbol not in markets:
            log.info("%s not in markets; skipping", symbol)
            continue
        try:
            maker, taker = adapter.fetch_fees(symbol)
        except Exception:
            maker, taker = 0.0, 0.0
        try:
            min_cost = float(adapter.min_notional(symbol))
        except Exception:
            min_cost = 0.0
        log.info(
            "%s min_cost=%.6g maker=%d bps taker=%d bps",
            symbol,
            min_cost,
            int(round(maker * 1e4)),
            int(round(taker * 1e4)),
        )


__all__ = ["markets_limits"]
