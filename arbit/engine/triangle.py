"""Utility helpers for triangular arbitrage: discovery, profitability, and sizing."""

from collections.abc import Mapping
from itertools import combinations
from typing import Any, Iterable, List, Tuple


def top(levels: List[Tuple[float, float]]) -> Tuple[float | None, float | None]:
    """Return best bid and ask from a list of ``(bid, ask)`` tuples.

    Args:
        levels: Bid/ask pairs, typically from order book snapshots.

    Returns:
        A tuple ``(bid, ask)`` where ``bid`` is the highest bid price and
        ``ask`` is the lowest ask price. ``(None, None)`` is returned when no
        levels are supplied.
    """

    if not levels:
        return None, None

    bids = [b for b, _ in levels if b is not None]
    asks = [a for _, a in levels if a is not None]
    best_bid = max(bids) if bids else None
    best_ask = min(asks) if asks else None
    return best_bid, best_ask


def net_edge_cycle(rates: Iterable[float]) -> float:
    """Return the product of ``rates`` minus one.

    The ``rates`` are multiplicative factors representing conversion steps
    around a trading cycle. A value greater than zero indicates a profitable
    cycle before fees.
    """

    product = 1.0
    for r in rates:
        product *= r
    return product - 1.0


def net_edge(ask_AB: float, bid_BC: float, bid_AC: float, fee: float) -> float:
    """Compute the net edge for a triangular arbitrage opportunity.

    Args:
        ask_AB: Ask price for the AB pair.
        bid_BC: Bid price for the BC pair.
        bid_AC: Bid price for the AC pair.
        fee:    Fee rate applied to each trade (e.g., 0.001 for 0.1%).

    Returns:
        The estimated percentage gain over the cycle after accounting for
        trading fees.
    """

    return net_edge_cycle([1.0 / ask_AB, bid_BC, bid_AC, (1 - fee) ** 3])


def discover_triangles_from_markets(
    ms: Mapping[str, Mapping[str, Any] | Any],
) -> list[list[str]]:
    """Return supported triangular markets from *ms*.

    Parameters
    ----------
    ms:
        Mapping of market symbols to metadata as returned by
        exchange clients' ``load_markets``. Each entry should contain
        ``base`` and ``quote`` fields. When absent, they are inferred by
        splitting the symbol on ``/``.

    Returns
    -------
    list[list[str]]
        Sorted list of unique triangles expressed as ``[A/B, A/C, C/B]``.
    """

    if not isinstance(ms, Mapping):
        return []

    markets: dict[str, tuple[str, str]] = {}
    for sym, info in ms.items():
        if not isinstance(sym, str):
            continue
        base: str | None = None
        quote: str | None = None
        if isinstance(info, Mapping):
            base = info.get("base")  # type: ignore[assignment]
            quote = info.get("quote")  # type: ignore[assignment]
        if not base or not quote:
            if "/" in sym:
                base, quote = sym.split("/", 1)
            else:
                continue
        base = str(base).upper()
        quote = str(quote).upper()
        markets[f"{base}/{quote}"] = (base, quote)

    base_map: dict[str, set[str]] = {}
    for base, quote in markets.values():
        base_map.setdefault(base, set()).add(quote)

    triangles: set[tuple[str, str, str]] = set()
    for base, quotes in base_map.items():
        for b, c in combinations(sorted(quotes), 2):
            sym_ab = f"{base}/{b}"
            sym_ac = f"{base}/{c}"
            sym_cb = f"{c}/{b}"
            sym_bc = f"{b}/{c}"
            if sym_cb in markets:
                triangles.add((sym_ab, sym_ac, sym_cb))
            if sym_bc in markets:
                triangles.add((sym_ac, sym_ab, sym_bc))

    return [list(tri) for tri in sorted(triangles)]


def size_from_depth(levels: List[Tuple[float, float] | list | dict]) -> float:
    """Return the smallest available quantity across depth levels.

    Accepts flexible level formats commonly returned by exchange clients:
    - ``(price, amount)`` tuples or lists (only first two fields used)
    - dicts with ``price``/``amount`` keys
    Unparseable entries are ignored.
    """

    if not levels:
        return 0.0

    qtys: list[float] = []
    for lvl in levels:
        qty = None
        # Sequence-like: [price, amount, ...]
        if isinstance(lvl, (list, tuple)) and len(lvl) >= 2:
            try:
                qty = float(lvl[1])
            except Exception:
                qty = None
        # Mapping-like: {"price": x, "amount": y}
        elif isinstance(lvl, dict):
            try:
                qty = float(lvl.get("amount"))  # type: ignore[arg-type]
            except Exception:
                qty = None
        if qty is not None:
            qtys.append(qty)
    return min(qtys) if qtys else 0.0
