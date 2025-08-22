# arbit.py

import os, ccxt, time, math

EX = "kraken"  # or binance, etc.
symAB, symBC, symAC = "ETH/USDT", "BTC/ETH", "BTC/USDT"
FEE = 0.001  # 0.1% taker as example; fetch from exchange
THRESH = 0.001  # 0.10% net minimum
QTY_USDT = 200  # per cycle notional cap

ex = getattr(ccxt, EX)(
    {
        "apiKey": os.getenv("API_KEY"),
        "secret": os.getenv("API_SECRET"),
        "enableRateLimit": True,
    }
)


def top(ob):
    # returns best bid, best ask
    bids = ob["bids"][0][0] if ob["bids"] else None
    asks = ob["asks"][0][0] if ob["asks"] else None
    return bids, asks


while True:
    obAB = ex.fetch_order_book(symAB, 10)
    obBC = ex.fetch_order_book(symBC, 10)
    obAC = ex.fetch_order_book(symAC, 10)

    bidAB, askAB = top(obAB)
    bidBC, askBC = top(obBC)
    bidAC, askAC = top(obAC)
    if None in (bidAB, askAB, bidBC, askBC, bidAC, askAC):
        time.sleep(0.2)
        continue

    # Cycle: USDT -> ETH -> BTC -> USDT
    gross = (1 / askAB) * bidBC * bidAC
    net = gross * (1 - FEE) ** 3 - 1

    if net >= THRESH:
        # size-based on depth: keep small, respect min notionals
        usdt = min(QTY_USDT, askAB * obAB["asks"][0][1])  # crude depth cap
        eth_qty = usdt / askAB
        btc_qty = eth_qty * bidBC

        # Place IOC/FOK market/limit with tight slippage controls
        # (pseudo; adapt to your exchange’s order flags)
        # ex.create_order(symAB, 'market', 'buy', eth_qty)
        # ex.create_order(symBC, 'market', 'sell', eth_qty)  # sell ETH for BTC
        # ex.create_order(symAC, 'market', 'sell', btc_qty)  # sell BTC for USDT
        print(f"Arb! est_net={net:.4%} notional≈${usdt:.2f}")
    time.sleep(0.05)
