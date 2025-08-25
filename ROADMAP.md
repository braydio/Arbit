# -- MAIN ROADMAP FOR DEVELOPMENT FEATURES

Basic CLI `live` loop is operational via `python -m arbit.cli live`; runs in dry-run mode unless configured otherwise.

    kraken_api_key: str | None = None
    kraken_api_secret: str | None = None

    notional_per_trade_usd: float = 200.0
    net_threshold_bps: float = 10.0
    max_slippage_bps: float = 8.0
    max_open_orders: int = 3
    dry_run: bool = True

    prom_port: int = 9109
    sqlite_path: str = "arbit.db"
    discord_webhook_url: str | None = None

    class Config:
        env_file = ".env"

settings = Settings()

````

`arbit/models.py`

```python
from dataclasses import dataclass
from typing import Literal

Side = Literal["buy", "sell"]

@dataclass(frozen=True)
class Triangle:
    # e.g. A=USDT, B=ETH, C=BTC; pairs are quoted as "BASE/QUOTE"
    AB: str   # e.g. ETH/USDT (buy ETH with USDT)
    BC: str   # e.g. BTC/ETH (sell ETH for BTC)
    AC: str   # e.g. BTC/USDT (sell BTC for USDT)

@dataclass
class OrderSpec:
    symbol: str
    side: Side
    qty: float
    tif: str = "IOC"
    type: str = "market"     # keep to market/IOC for speed; upgrade later

@dataclass
class Fill:
    order_id: str
    symbol: str
    side: Side
    qty: float
    price: float
    fee: float
````

---

# 2) Exchange Abstraction

`arbit/adapters/base.py`

```python
from abc import ABC, abstractmethod
from typing import Any, Dict, Tuple, List
from arbit.models import OrderSpec, Fill

class ExchangeAdapter(ABC):
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def fetch_orderbook(self, symbol: str, depth: int = 10) -> Dict[str, Any]: ...

    @abstractmethod
    def fetch_fees(self, symbol: str) -> Tuple[float, float]:
        """Return (maker, taker) as decimals, e.g. 0.001 for 0.1%."""

    @abstractmethod
    def min_notional(self, symbol: str) -> float:
        """Return min quote amount required by venue for symbol."""

    @abstractmethod
    def create_order(self, spec: OrderSpec) -> Fill:
        """Place single order and return a Fill (simulate in dry-run)."""

    @abstractmethod
    def balances(self) -> Dict[str, float]: ...
```

`arbit/adapters/ccxt_adapter.py`

````python
import os, time
import ccxt
from arbit.adapters.base import ExchangeAdapter
from arbit.models import OrderSpec, Fill
from arbit.config import settings

class CcxtAdapter(ExchangeAdapter):
    def __init__(self, ex_id: str):
        ex_class = getattr(ccxt, ex_id)
        self.ex = ex_class({
            "apiKey": os.getenv(f"{ex_id.upper()}_API_KEY"),
            "secret": os.getenv(f"{ex_id.upper()}_API_SECRET"),
            "enableRateLimit": True,
        })
        # Alpaca-specific host override if provided
        if ex_id == "alpaca" and settings.alpaca_base_url:
            self.ex.urls["api"] = settings.alpaca_base_url

        self._fee_cache = {}

    def name(self) -> str: return self.ex.id

    def fetch_orderbook(self, symbol: str, depth: int = 10):
        return self.ex.fetch_order_book(symbol, depth)

    def fetch_fees(self, symbol: str):
        # Try cache or exchange markets metadata; fallback to taker for safety
        if symbol in self._fee_cache: return self._fee_cache[symbol]
        m = self.ex.market(symbol)
        maker = m.get("maker", self.ex.fees.get("trading", {}).get("maker", 0.001))
        taker = m.get("taker", self.ex.fees.get("trading", {}).get("taker", 0.001))
        self._fee_cache[symbol] = (maker, taker)
        return maker, taker

    def min_notional(self, symbol: str) -> float:
        m = self.ex.market(symbol)
        limits = m.get("limits", {})
        cost = limits.get("cost", {}).get("min", 1.0)  # $1 default if unknown
        return float(cost or 1.0)

    def create_order(self, spec: OrderSpec) -> Fill:
        if settings.dry_run:
            # Simulate immediate fill at top of book
            ob = self.fetch_orderbook(spec.symbol, 1)
            price = ob["asks"][0][0] if spec.side == "buy" else ob["bids"][0][0]
            fee_rate = self.fetch_fees(spec.symbol)[1]  # taker
            fee = price * spec.qty * fee_rate
            return Fill("dryrun", spec.symbol, spec.side, spec.qty, price, fee)

        # Live order
        params = {"timeInForce": spec.tif}
        o = self.ex.create_order(spec.symbol, spec.type, spec.side, spec.qty, None, params)
        # Fetch a trade fill price; some venues return avg price directly
        filled = float(o.get("filled", spec.qty))
        price = float(o.get("average") or o.get("price") or 0.0)
        fee_cost = 0.0                                                                             ribe = {
            "method": "subscribe",                                                         []
                    asks = data.get("asks") or []                                                      one)
```                                                                                                                                                              Tuple[float, float]) -> float:
    """Crude sizing: cap by top ask depth on first leg."""                                    try_tri(adapter: ExchangeAdapter, tri: Triangle) -> dict | None:
    obAB = adapter.fetch_orderbook(tri.AB, 10)                           _bps / 10000.0
    if net < thresh:              buy ETH with USDT
        f2 = adapter.create_order(o2)  # sell ETH for BTC         i,
        "net_est": net, TEXT NOT NULL,
  symbol TEXT NOT NULL,                                                                    str):
    return CcxtAdapter(venue)                                                         )
def fitness(venue: str = "alpaca", secs: int = 20):
    a = make_adapter(venue)                                              dockerfile
FROM python:3.11-slim                                                  env_file: .env
    volumes: ["./data:/data"]                                   ]
    restart: unless-stopped                                 ue alpaca
Restart=always                                         e
def test_edge_increases_with_better_quotes(): re-fund both sides to avoid transfers.
* (Optional) Add a **hedger**: if one leg it.)
                                      tiny** `NOTIONAL_PER_TRADE_USD` (e.g., 10) for 15–30 minutes.
5. Bump notional slowly; add the erate the repo skeleton and tailor the **symbol lists** to the exact pairs live on your Alpaca + Kraken accounts (and add a Discord alert hook) — but the above is ready for Codex to implement as-is.
**Kraken** service and compare PnL and hit-rate.
6. Enable alerting + inventory caps before scaling.

---

If you want, I can also gen
---

# 13) What to Run First (step-by-step)

1. **Clone + .env** → put keys, keep `DRY_RUN=true`.
2. `python -m arbit.cli fitness --venue alpaca --secs 30` and for kraken: verify books.
3. `python -m arbit.cli live --venue alpaca` (still dry-run) → confirm logs, Prometheus metrics, SQLite rows.
4. Flip `DRY_RUN=false` with **fails on Venue A, place a hedge on Venue B to flatten inventory.

---

# 12) Optional Phase 2: Stablecoin “Auto-Allocator” (Aave)

If you want the stable, set-and-forget yield piece:

````

arbit/
└─ defi/
├─ aave_alloc.py # deposit/withdraw + APY poll
└─ cli.py # mf-defi deposit/withdraw/status

```


Keep it simple: **supply USDC** to Aave v3 on your preferred chain. Add a tiny rule: “Move only if projected 30-day APY gain – gas ≥ threshold.” (We can wire this in later; the arb bot doesn’t depend on      et edges across venues and sends the cycle where **net\_est – fees – slippage** is highest.
* P
    a = net_edge(ask_AB=2000, bid_BC=0.05, bid_AC=60000, fee_rate=0.001)
    b = net_edge(1995, 0.0502, 60020, 0.001)
    assert b > a
```

`tests/test_triangle.py`

```pytho n
from arbit.engine.triangle import size_from_depth
def test_sizing_respects_depth():

    qty = size_from_depth(1000, (2000, 0.2))  # price=2                                        000, depth=0.2 ETH
    assert qty <= 0.18     # 90% of depth
```

---

# 11) Cross-Exchange Mode (when ready)

- Run **both** venues live.
- Add a **routing layer** that compares triangle n

[Install]
WantedBy=multi-user.target

````

Prometheus scrape                                 example:

```yaml
- job_name: 'arbit'
  static                                _configs:
    - targets: ['localhost:9109','localhost:9110']
````

---

# 10) Tests You Can Run Today

`tests/test_math.py`

```python
from arbit.engine.triangle import net_edge
    ports: ["9110:9109"]
    environment:
      - PROM_PORT                                  =9109
    command: ["python","-m","arbit.cli","live","--venue","kraken"]
```

**sys temd (optional)**

```
[Unit]
Description=arbit Alpaca
After=network-online.target

[Service]
User=money
WorkingDirectory=                                  /opt/money-farmer
EnvironmentFile=/opt/money-farmer/.env
ExecStart=/usr/bin/python -m arbit.cli live --ven
    restart:                                               unless-stopped
    ports: ["9109:9109"]
    command: ["python","-m","arbit.cli","live","                                              --venue","alpaca"]
  mf-kraken:
    build: .
    env_file: .env
    volumes: ["./data:/data"
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN pip install --no-cache-dir ccxt websockets pydantic typer prometheus-client orjson
COPY arbit ./arbit:wq
COPY pyproject.toml .env.example ./
CMD ["python", "-m", "arbit.cli", "live", "--venue", "alpaca"]
```

`docker-compose.yml`

```yaml
services:
  mf-alpaca:
    build: .
    nd don’t re-fire a leg if you got a late success.
* *                                                 *Discord alerts** for error bursts or negative PnL streaks.

(You can add these as small checks ins                                                 ide `try_tri` and the main `live` loop.)

---

# 9) Docker & Ops

`Dockerfile`

```

    cx = connect(settings.sqlite_path)
    prom_start(settings.prom_p                             ort)
    log.info(f"Starting live loop on {venue} (dry_run={settings.dry_run})")
    w                             hile True:
        for tri in DEFAULT_TRIANGL                             ES:
            res = try_tri(a, tri)
            if not res: continue
            if "error"                              in res:
                ORDERS_TOTAL.labels(venue, "error").inc()
                log.error(res["error"])                             ; continue
            ORDERS_TOTAL.labels(venue, "ok").inc()
            PROFIT_TOTAL.labels(venue).set(res["realized_usdt"])
            for f in res                             ["fills"]: insert_trade(cx, venue, f)
            insert_cycle(cx, venue, tri, res["net_est"], res[                             "realized_usdt"])
            log.info(f"{venue} {tri} net_est={res['net_est']:.3%} realized={                             res['realized_usdt']:.2f} USDT")
        tim                             e.sleep(0.05)

if **name** == "**main**":
app()

````

**Run it:**

```ba                             sh
# install
pip install ccxt websockets pydantic typer prometheus-client orjson

# copy .env.example                              to .env and fill keys
python -m arbit.cli fitness --venue alpaca --secs 30
python -m arbit.cli f                             itness --venue kraken --secs 30

# dry-run live
p                             ython -m arbit.cli live --venue alpaca
python -m arbit.cli live --venue kraken
````

---

                             # 8) Risk Controls You’ll Actually Use

- **IOC everywhere** for all three legs to avoid get ting stuck.
- **Min notional** guard per venue/pair (`adapter.min_notional()`).
- **M ax open orders** limiter (back-off if latency grows).
- -                             *Inventory caps**: refuse cycles if balances would breach per-asset caps.
- **Volatility kill-switch**: i f spread widens beyond X bps or WS desync detected → pause.
- **Idempotency**: attach client IDs a
  """Record top-of-book & spre ads; no orders."""
  a = make_adapter(venue)
  syms = {s for t in DEFAULT_TRIANGLES for s in (t.AB,t.BC,t.AC)}
  t0 = time.time()
  while time.time() - t0 < secs:
  for s in syms:
  ob = a.fetch_orderbook(s, 5)  
   if not ob["bids"] or not ob["asks"]:  
   log.warning(f"[{venue}] no book for {s}")
  else:
  b, a1 = ob["bids"][0][0], ob["asks"][0][0]
  log.info(f"[{venue}] {s} spread={((a1-b)/a1)\*10000:.1f} bps")
  time.sleep(0.3)

@app.command()
def live(venue: str = "alpaca"):

@app.command( nfig(level=settings.log_level)

DEFAULT_TRIANGLES = [
# BTC/ETH/USDT triangle example
Triangle(AB="ETH/USDT", BC="BTC/ETH", AC="BTC/USDT"),
# BTC/ETH/USDC
Triangle(AB="ETH/USDC", BC="BTC/ETH", AC="BTC/USDC"),
]

ORDERS_TOTAL = Counter("mf_orders_total", "Orders attempted", ["venue","result"])
PROFIT_TOTAL = Gauge("mf_profit_total_usdt", "Gross realized PnL in USDT", ["venue"])
latency_ms = Gauge("mf_loop_latency_ms", "Main loop latency")

def start_metrics_server(port: int): start_http_server(port)

````

---

# 7) CLI & Main Loop

`arbit/cli.py`

```python
import time, typer, logging
from arbit.config import settings
from arbit.adapters.ccxt_adapter import CcxtAdapter
from arbit.engine.executor import try_tri
from arbit.models import Triangle
from arbit.metrics.exporter import start_metrics_server, ORDERS_TOTAL, PROFIT_TOTAL
from arbit.persistence.db import connect, insert_trade, insert_cycle

app = typer.Typer()
log = logging.getLogger("mf"); logging.basicCo    net_est, realized)
    )
````

`arbit/metrics/exporter.py`

````python
from prometheus_client import start_http_server, Counter, Gauge
arb_     enue, fill.symbol, fill.side, fill.qty, fill.price, fill.fee, getattr(fill, "order_id", None))
    )

def insert_cycle(cx, venue, tri, net_est, realized):
    cx.execute(
        "INSERT INTO cycles (ts,venue,ab,bc,ac,net_est,realized_usdt) VALUES (?,?,?,?,?,?,?)",
        (int(time.time()), venue, tri.AB, tri.BC, tri.AC,     TEXT NOT NULL, bc TEXT NOT NULL, ac TEXT NOT NULL,
  net_est REAL, reali                                                                                        zed_usdt REAL
);
"""

def connect(path: str):
    cx = sqlite3.connect(path, isolation_level=N                                                                                        one)
    cx.executescript(DDL)
    return cx

def insert_trade(cx, venue, fill):
    cx.execute(
        "INSERT INTO trades (ts,venu                                                                                        e,symbol,side,qty,price,fee,client_id) VALUES (?,?,?,?,?,?,?,?)",
        (int(time.time()), v
  side TEXT NOT NULL,
  qty REAL NOT NULL,
  price REAL NOT NULL,
  fee REAL NOT NULL,
  client_id TEXT
);
CREATE TABLE IF NOT EXISTS cycles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  venue TEXT NOT NULL,
  ab                                                                                                   nce (SQLite) & Metrics

`arbit/persiste                                                                                                 nce/db.py`

```python
import sqlite3, time
from typing import Any, Iterable

DDL = """
CREATE                                                                                                  TABLE IF NOT EXISTS trades (
  id I                                                                                                 NTEGER PRIMARY KEY AUTOINCREMENT,
  ts INTEGER NOT NULL,
  venue
        "fills": fills,
        "realized_usdt": realized,
    }
````

> Note: Depending on the exchange, **`create_order`** returns price/qty in base or quote; adapt the realized PnL math once you inspect the live response. The scaffolding is intentionally explicit so it’s easy to fix per venue.

---

# 6) Persiste venue supports it

        return {"error": str(e), "net_est": net, "tri": tri}

    # Com                                                                        pute realized PnL
    usdt_out = f1.price * f1.qty + f1.fee
    btc_in   = f2.price * f2.qty                                                                          # approximate; use base/quote carefully per venue result
                                                                            usdt_in  = f3.price * f3.qty - f3.fee
    realized = usdt_in - usdt_out

    return {
        "tri": tr
        f3 = adapter.create_order(o3)  # sell BTC for USDT
        fills = [f1, f2, f3]
    except Exception as e:
        # TODO: add cancel/cleanup logic if                                                                                                         IOC", type="market")
    # ETH->BTC qty is qtyB * bidBC / ???  (market order qty is in                                                                                                                       BASE)
    qtyC = qtyB * bidBC  # approxima                                                                                                                      te (we will place by BASE of BC)
    o2 = OrderSpec(symbol=tri.BC, side="sell", qty=qtyB, tif=                                                                                                                      "IOC", type="market")
    o3 = OrderSpec(symbol=tri.AC, side="sell", qty=qtyC, tif="IOC",                                                                                                                       type="market")

    fills: list[Fill] = []
    try:
        f1 = adapter.create_order(o1)  #
        return None

    # Sizing (leg-1 constrained by top ask depth)
    ask_price, ask_qty = obAB["asks"][0]
    qtyB = size_from_depth(settings.notional_per_trade_usd, (ask_price, ask_qty))

    # Enforce min notional, slippage headroom
    min_notional = adapter.min_notional(tri.AB)
    if (qtyB * ask_price) < min_notional:
        return None

    # Prepare 3 IOC market orders
    o1 = OrderSpec(symbol=tri.AB, side="buy",  qty=qtyB, tif="                                                                          p(obAB)
    bidBC, askBC = top(obBC)
    bidAC, askAC = top(obAC)
    if None in (bi                                                                                                    dAB, askAB, bidBC, askBC, bidAC, askAC):
        return None

    # Use taker fee as wors                                                                                                    t-case
    fee = adapter.fetch_fees(tri.AB)[1]
    net = net_edge(askAB, bidBC, bi                                                                                                    dAC, fee_rate=fee)

    thresh = settings.net_threshold
    obBC = adapter.fetch_orderbook(tri.BC, 10)
    obAC = adapter.fetch_orderbook(tri.AC, 10)

    bidAB, askAB = to                                                              ty_by_depth, desired_qty)

````

---

# 5) Atomic                                                                                                  Execution & Risk Rails

`arbit/engine/executor.py`

```python
from arbit.adapters.bas                                                                                                 e import ExchangeAdapter
from arbit.models import Triangle, OrderSpec, Fill
from arbit.eng                                                                                                 ine.triangle import top, net_edge, size_from_depth
from arbit.config import settings

def
    price, qty = ask_AB
    if not price or not qty: return 0.0
    max_qty_by_depth = qty * 0.9
    desired_qty = (notional_usd / price)
    return min(max_q     _BC * bid_AC
    net after 3 taker legs = gross                                                                                                                                                                  * (1-fee)^3 - 1
    """
    gross = (1.0 / ask_AB) * bid_BC * bid_AC
    net = gross                                                                                                                                                                  * (1 - fee_rate) ** 3 - 1.0
    return net

def size_from_depth(notional_usd: float, ask_AB:

> Start this alongside the engine to get near-real-time best bid/ask without polling.

---

# 4) Triangle Detection & Math

`arbit/engine/triangle.py`

```python
from arbit.models import Triangle
from typing import Dict, Tuple

def top(ob):
    bid = ob["bids"][0][0] if ob["bids"] else None
    ask = ob["asks"][0][0] if ob["asks"] else None
    return bid, ask

def net_edge(ask_AB: float, bid_BC: float, bid_AC: float, fee_rate: float) -> float:
    """
    Cycle: A(USDT) -> B(ETH) -> C(BTC) -> A(USDT)
    gross multiple = (1/ask_AB) * bid                                                                           def top(self, symbol: str) -> Tuple[float | None, float | None]:
        b = self.books[symbol]["bi                                                                                                                                ds"]
        a = self.books[symbol]["asks"]
        return (b[0][0] if b else None, a[0][0] if a else N
                    if bids: book["bids"].appendleft((float(bids[0][0]), float(bids[0][1])))
                    if asks: book["asks"].appendleft((float(asks[0][0]), float(asks[0][1])))

                                                                                                     ws:
                data = json.loads(msg)
                if isinstance(data, dict) and data.get("c                                                                                                                                                        hannel") == "book":
                    sym = data["symbol"]
                    book = self.books[sym]
                    bids = data.get("bids") or
            "params": {
                "channel": "book",
                "symbol": self.symbols,
                "depth": 10,
            }
        }
        async with websockets.connect(url, ping_interval=20) as ws:
            await ws.send(json.dumps(subscribe))
            async for msg in                                                                                                 elf.books: Dict[str, Dict[str, deque]] = {s: {"bids": deque(maxlen=1), "asks": deque(maxlen=1)} for s in symbols}

    async def run(self):
        url = "wss://ws.kraken.com/v2"
        subsc
        for f in o.get("fees", []):
            fee_cost += float(f.get("cost") or 0.0)
        return Fill(o["id"], spec.symbol, spec.side, filled, price, fee_cost)

    def balances(self):
        b = self.ex.fetch_balance()
        return {k: float(v) for k, v in b.get("total", {}).items() if float(v or 0) > 0}
````

> That adapter works for **Alpaca** and **Kraken** via `ccxt`. You can later bolt on a **native Kraken WS** orderbook for speed (next section).

---

# 3) Fast Orderbooks (optional, Kraken WS)

`arbit/adapters/kraken_ws.py`

```python
import asyncio, json, websockets
from collections import deque
from typing import Dict, List, Tuple

class KrakenWSBook:
    def __init__(self, symbols: List[str]):
        self.symbols = symbols
        san abstractions, risk rails, metrics, containerization, and a path to add a **stablecoin allocator** later.

---

# 🧭 Architecture at a Glance

```

money-farmer/
├─ README.md
├─ .env.example
├─ docker-compose.yml
├─ Dockerfile
├─ pyproject.toml # or requirements.txt
├─ arbit/
│ ├─ **init**.py
│ ├─ config.py # pydantic settings
│ ├─ models.py # dataclasses (Triangle, Fill, Order)
│ ├─ utils.py # math/fees helpers
│ ├─ persistence/
│ │ ├─ db.py # sqlite schema + simple DAO
│ ├─ metrics/
│ │ └─ exporter.py # Prometheus HTTP server
│ ├─ adapters/
│ │ ├─ base.py # ExchangeAdapter ABC
│ │ ├─ ccxt_adapter.py # Alpaca/Kraken via ccxt
│ │ └─ kraken_ws.py # native Kraken WS orderbook (optional speed)
│ ├─ engine/

│ │ ├─ triangle.py # detection & sizing
│ │ └─ executor.py # atomic 3-leg execution, risk rails
│ └─ cli.py # Typer CLI: fitness-test / dry-run / live
└─ tests/
├─ test_math.py
├─ test_triangle.py
└─ test_executor.py

````

---

# 0) Prereqs

* Create/fund **Alpaca** and **Kraken** accounts.
* Generate API keys with **trade** permission (withdrawal whitelist recommended).
* Fund with USDT/USDC + a bit of BTC/ETH for rebalance.

* Python 3.11+, `pip install ccxt websockets pydantic typer prometheus-client aiosqlite orjson`.

`.env.example`

```bash
# General
ENV=dev
LOG_LEVEL=INFO

# Exchanges
EXCHANGES=alpaca,kraken

# Alpaca
ALPACA_API_KEY=...
ALPACA_API_SECRET=...
ALPACA_BASE_URL=https://api.alpaca.markets

# Kraken
KRAKEN_API_KEY=...
KRAKEN_API_SECRET=...

# Strategy
NOTIONAL_PER_TRADE_USD=200
NET_THRESHOLD_BPS=10           # 10 bps = 0.10%
MAX_SLIPPAGE_BPS=8
MAX_OPEN_ORDERS=3
DRY_RUN=true                   # flip to false for live

# Metrics / DB / Alerts
PROM_PORT=9109
SQLITE_PATH=/data/arbit.db
DISCORD_WEBHOOK_URL=
````

---

# 1) Config & Models

`arbit/config.py`

```python
from pydantic import BaseSettings, Field
from typing import List

class Settings(BaseSettings):
    env: str = "dev"
    log_level: str = "INFO"

    exchanges: List[str] = Field(default_factory=lambda: ["alpaca", "kraken"])

    alpaca_api_key: str | None = None
    alpaca_api_secret: str | None = None
    alpaca_base_url:
```
