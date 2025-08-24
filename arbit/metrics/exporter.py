from prometheus_client import Counter, Gauge, start_http_server

arb_cycles = Counter("arbit_cycles", "Arb cycles", ["venue", "result"])
pnl_gross = Gauge("arbit_pnl_usdt", "Realized PnL (USDT)", ["venue"])


def start(port: int):
    start_http_server(port)
