"""Simple triangular arbitrage monitor with optional TUI interface.

The script polls three markets on a single exchange to detect a
USDT→ETH→BTC→USDT cycle. When the net return exceeds the configured
threshold, the opportunity is logged.  A minimal curses based TUI can be
launched to visualise the live spreads and profit estimate.
"""

from __future__ import annotations

import argparse
import os
import time
from typing import Dict, Tuple, TYPE_CHECKING

import curses

if TYPE_CHECKING:  # pragma: no cover - for type checking only
    import ccxt  # type: ignore

EX = "kraken"  # default exchange; configurable via --exchange
SYM_AB, SYM_BC, SYM_AC = "ETH/USDT", "BTC/ETH", "BTC/USDT"
FEE = 0.001  # 0.1% taker fee; fetch from exchange for real usage
THRESH = 0.001  # 0.10% minimum net threshold
QTY_USDT = 200  # per cycle notional cap


def top(ob: Dict[str, list]) -> Tuple[float | None, float | None]:
    """Return best bid and ask prices from a CCXT order book."""

    bid = ob["bids"][0][0] if ob.get("bids") else None
    ask = ob["asks"][0][0] if ob.get("asks") else None
    return bid, ask


def compute_net(bid_ab: float, ask_ab: float, bid_bc: float, ask_bc: float,
                bid_ac: float, ask_ac: float, fee: float = FEE) -> float:
    """Compute net gain of the USDT→ETH→BTC→USDT cycle."""

    gross = (1 / ask_ab) * bid_bc * bid_ac
    return gross * (1 - fee) ** 3 - 1


def run_loop(ex: "ccxt.Exchange", cycles: int | None = None,
             screen: curses.window | None = None) -> None:
    """Continuously poll order books and report arbitrage opportunities.

    Args:
        ex: Initialised CCXT exchange instance.
        cycles: Number of iterations to run. ``None`` runs forever.
        screen: Optional curses window for TUI display.
    """

    i = 0
    while cycles is None or i < cycles:
        ob_ab = ex.fetch_order_book(SYM_AB, 10)
        ob_bc = ex.fetch_order_book(SYM_BC, 10)
        ob_ac = ex.fetch_order_book(SYM_AC, 10)

        bid_ab, ask_ab = top(ob_ab)
        bid_bc, ask_bc = top(ob_bc)
        bid_ac, ask_ac = top(ob_ac)
        if None in (bid_ab, ask_ab, bid_bc, ask_bc, bid_ac, ask_ac):
            time.sleep(0.2)
            continue

        net = compute_net(bid_ab, ask_ab, bid_bc, ask_bc, bid_ac, ask_ac)
        if net >= THRESH:
            usdt = min(QTY_USDT, ask_ab * ob_ab["asks"][0][1])
            message = f"Arb! est_net={net:.4%} notional≈${usdt:.2f}"
        else:
            message = f"net={net:.4%}"

        if screen:
            screen.erase()
            screen.addstr(0, 0, f"{SYM_AB}: bid {bid_ab:.2f} / ask {ask_ab:.2f}")
            screen.addstr(1, 0, f"{SYM_BC}: bid {bid_bc:.2f} / ask {ask_bc:.2f}")
            screen.addstr(2, 0, f"{SYM_AC}: bid {bid_ac:.2f} / ask {ask_ac:.2f}")
            screen.addstr(4, 0, message)
            screen.refresh()
        else:
            print(message)

        i += 1
        time.sleep(0.05)


def main() -> None:
    """Entry point for CLI usage."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exchange", default=EX, help="ccxt exchange id")
    parser.add_argument("--tui", action="store_true", help="enable curses UI")
    parser.add_argument("--cycles", type=int, default=None,
                        help="number of iterations to run")
    args = parser.parse_args()

    import ccxt  # type: ignore

    ex_class = getattr(ccxt, args.exchange)
    ex = ex_class(
        {
            "apiKey": os.getenv("API_KEY"),
            "secret": os.getenv("API_SECRET"),
            "enableRateLimit": True,
        }
    )

    if args.tui:
        curses.wrapper(lambda scr: run_loop(ex, args.cycles, scr))
    else:
        run_loop(ex, args.cycles)


if __name__ == "__main__":
    main()
