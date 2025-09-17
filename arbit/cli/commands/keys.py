"""API key validation CLI commands."""

from __future__ import annotations

from arbit.config import settings

from ..core import app, log
from ..utils import _build_adapter


@app.command("keys:check")
@app.command("keys_check")
def keys_check() -> None:
    """Validate exchange credentials by fetching a sample order book."""

    for venue in settings.exchanges:
        try:
            adapter = _build_adapter(venue, settings)
            markets = adapter.load_markets()
            symbol = (
                "BTC/USDT"
                if "BTC/USDT" in markets
                else "BTC/USD"
                if "BTC/USD" in markets
                else next(iter(markets))
            )
            orderbook = adapter.fetch_orderbook(symbol, 1)
            bids = orderbook.get("bids", [])
            asks = orderbook.get("asks", [])
            bid_price = bids[0][0] if bids else "n/a"
            ask_price = asks[0][0] if asks else "n/a"
            log.info(
                "[%s] markets=%d %s %s/%s",
                adapter.name(),
                len(markets),
                symbol,
                bid_price,
                ask_price,
            )
        except Exception as exc:
            log.error("[%s] ERROR: %s", venue, exc)


__all__ = ["keys_check"]
