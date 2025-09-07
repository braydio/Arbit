"""Command line interface utilities.

This module exposes Typer-based commands for interacting with the
arbitrage engine.  Helper functions for metrics and persistence are
imported here so tests can easily monkeypatch them.
"""

import asyncio
import json
from datetime import datetime, timezone
import logging
import sys
import time
import urllib.request

import typer
from arbit import try_triangle
from arbit.adapters.ccxt_adapter import CCXTAdapter
from arbit.config import settings
from arbit.engine.executor import stream_triangles, try_triangle
from arbit.metrics.exporter import (
    CYCLE_LATENCY,
    ERRORS_TOTAL,
    FILLS_TOTAL,
    ORDERS_TOTAL,
    PROFIT_TOTAL,
    SKIPS_TOTAL,
    YIELD_ALERTS_TOTAL,
    YIELD_APR,
    YIELD_CHECKS_TOTAL,
    YIELD_DEPOSITS_TOTAL,
    YIELD_ERRORS_TOTAL,
    YIELD_WITHDRAWS_TOTAL,
    start_metrics_server,
)
from arbit.models import Fill, Triangle, TriangleAttempt
from arbit.persistence.db import init_db, insert_attempt, insert_fill, insert_triangle


class CLIApp(typer.Typer):
    """Custom Typer application that prints usage on bad invocation."""

    # ------------------------------------------------------------------
    def _unique_commands(self) -> dict[str, dict[str, object]]:
        """Return mapping of canonical command names to command/aliases."""

        mapping: dict[str, dict[str, object]] = {}
        for name, cmd in self.commands.items():
            canonical = name.replace("_", ":")
            info = mapping.setdefault(canonical, {"command": cmd, "aliases": []})
            info["aliases"].append(name)
        return mapping

    def main(self, args: list[str] | None = None):
        """Run the CLI with *args*, handling help flags and bad input.

        Parameters
        ----------
        args:
            Optional list of command-line arguments.  Defaults to
            ``sys.argv[1:]`` when not provided.

        The method detects ``--help`` and ``--help-verbose`` flags before
        delegating to Typer's normal processing.  ``--help`` prints a short
        summary of available commands while ``--help-verbose`` provides a
        more detailed reference including flags and sample output.
        """

        if args is None:
            args = sys.argv[1:]

        if args and args[0] == "--help-verbose":
            self._print_verbose_help()
            raise SystemExit(0)

        if args and args[0] == "--help":
            self._print_basic_help()
            raise SystemExit(0)

        if not args or args[0] not in self.commands:
            typer.echo("Usage: arbit.cli [COMMAND]")
            if self.commands:
                typer.echo("Commands:")
                for cname in sorted(self._unique_commands()):
                    typer.echo(f"  {cname}")
            raise SystemExit(0 if not args else 1)
        return super().main(args)

    # ------------------------------------------------------------------
    def _print_basic_help(self) -> None:
        """Print a short summary of available commands."""

        typer.echo("Usage: python -m arbit.cli [--help | --help-verbose] COMMAND [ARGS]")
        typer.echo("\nAvailable commands:")
        for cname, info in sorted(self._unique_commands().items()):
            desc = (info["command"].callback.__doc__ or "").strip().splitlines()[0]
            aliases = [
                a.replace("_", ":")
                for a in info["aliases"]
                if a.replace("_", ":") != cname
            ]
            alias_str = f" (aliases: {', '.join(sorted(aliases))})" if aliases else ""
            typer.echo(f"  {cname:<12} {desc}{alias_str}")
        typer.echo("\nTip: run --help-verbose for flags and examples.")

    # ------------------------------------------------------------------
    @staticmethod
    def _print_verbose_help() -> None:
        """Print detailed command reference with flags and examples."""

        typer.echo("Command reference:\n")
        typer.echo("Global: --help (short list), --help-verbose (this view)\n")

        typer.echo(
            "keys:check\n"
            "  Validate exchange credentials by fetching a sample order book.\n"
            "  Aliases: keys:check, keys_check\n"
            "  Sample output:\n"
            "    [alpaca] markets=123 BTC/USDT 60000/60010\n"
        )

        typer.echo(
            "fitness\n"
            "  Monitor order books to gauge spread without trading. Optionally simulate executions.\n"
            "  Flags (all optional):\n"
            "    --venue TEXT              Exchange to query (default: alpaca)\n"
            "    --secs INTEGER            Seconds to run (default: 20)\n"
            "    --simulate/--no-simulate  Try dry-run triangle executions (default: no-simulate)\n"
            "    --persist/--no-persist    Persist simulated fills to SQLite (used with --simulate)\n"
            "    --dummy-trigger           Inject one synthetic profitable triangle (with --simulate)\n"
            "    --help-verbose            Print extra context about fitness output\n"
            "  Sample output:\n"
            "    alpaca ETH/USDT spread=10.0 bps\n"
            "    alpaca [sim] Triangle(ETH/USDT, ETH/BTC, BTC/USDT) net=0.15% PnL=0.05 USDT\n"
        )

        typer.echo(
            "live\n"
            "  Continuously scan for profitable triangles and execute trades.\n"
            "  Flags (optional):\n"
            "    --venue TEXT   Exchange to trade on (default: alpaca)\n"
            "    --help-verbose Print extra context about live output semantics\n"
            "  Sample output:\n"
            "    alpaca ETH/BTC net=0.5% PnL=0.10 USDT\n"
        )

        typer.echo(
            "markets:limits\n"
            "  List market min-notional and fees to help size trades.\n"
            "  Aliases: markets:limits, markets_limits\n"
            "  Flags (all optional):\n"
            "    --venue TEXT     Exchange to query (default: alpaca)\n"
            "    --symbols TEXT   CSV filter (e.g., BTC/USDT,ETH/USDT); default = triangle symbols\n"
            "  Sample output:\n"
            "    BTC/USDT min_cost=5.0 maker=10 bps taker=10 bps\n"
        )

        typer.echo(
            "config:recommend\n"
            "  Suggest starter Strategy settings based on venue data.\n"
            "  Aliases: config:recommend, config_recommend\n"
            "  Flags (optional):\n"
            "    --venue TEXT   Exchange to query (default: alpaca)\n"
            "  Sample output:\n"
            "    Recommend: NOTIONAL_PER_TRADE_USD=10 NET_THRESHOLD_BPS=25 MAX_SLIPPAGE_BPS=8 DRY_RUN=true\n"
        )

        typer.echo(
            "yield:collect\n"
            "  Deposit idle USDC to Aave v3 to earn yield (beta).\n"
            "  Aliases: yield:collect, yield_collect\n"
            "  Flags (optional):\n"
            "    --asset TEXT        Asset to deposit (default: USDC)\n"
            "    --min-stake INTEGER Minimum token units to deposit (default: settings.min_usdc_stake)\n"
            "    --reserve-usd FLOAT Keep this much USD in wallet (default: settings.reserve_amount_usd; reserve_percent also applied)\n"
            "    --help-verbose      Print extra context and environment requirements\n"
            "  Environment:\n"
            "    RPC_URL, PRIVATE_KEY; USDC/Pool addresses from settings.\n"
            "  Sample output:\n"
            "    [dry-run] would deposit 150.00 USDC to Aave (reserve=50.00)\n"
        )

        typer.echo(
            "yield:watch\n"
            "  Periodically check APR sources and alert if a better yield exists.\n"
            "  Aliases: yield:watch, yield_watch\n"
            "  Flags (optional):\n"
            "    --asset TEXT        Asset symbol (default: USDC)\n"
            "    --sources TEXT      CSV or JSON array of URLs returning {provider, asset, apr_percent}\n"
            "    --interval FLOAT    Poll interval in seconds (default: 60)\n"
            "    --apr-hint FLOAT    Current provider APR used as baseline for alerts\n"
            "    --min-delta-bps INT Minimum APR improvement to alert (default: 50 bps)\n"
            "  Sample output:\n"
            "    Better yield available for USDC: foo 5.10% >= current 4.50% + 0.50%\n"
        )


app = CLIApp()
log = logging.getLogger("arbit")
logging.basicConfig(level=settings.log_level)


def _triangles_for(venue: str) -> list[Triangle]:
    data = getattr(settings, "triangles_by_venue", {}) or {}
    triples = data.get(venue)
    if not triples:
        # Fallback defaults if config missing or tests stub settings
        triples = [
            ["ETH/USDT", "BTC/ETH", "BTC/USDT"],
            ["ETH/USDC", "BTC/ETH", "BTC/USDC"],
        ]
    return [Triangle(*t) for t in triples]


def _build_adapter(venue: str, _settings=settings):
    """Factory for constructing exchange adapters.

    Parameters
    ----------
    venue:
        Exchange identifier understood by the underlying adapter.
    _settings:
        Settings object used to configure the adapter (unused for now).
    """

    return CCXTAdapter(venue)


def _notify_discord(venue: str, message: str) -> None:
    """Send a simple message to Discord webhook if configured.

    Errors are swallowed; this is best-effort only.
    """
    url = settings.discord_webhook_url
    if not url:
        return
    data = json.dumps({"content": message}).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=3) as _:
            return
    except Exception:
        # Avoid spamming logs; bump an error metric instead
        try:
            ERRORS_TOTAL.labels(venue, "discord_send").inc()
        except Exception:
            pass


@app.command("yield:collect")
@app.command("yield_collect")
def yield_collect(
    asset: str = "USDC",
    min_stake: int | None = None,
    reserve_usd: float | None = None,
    help_verbose: bool = False,
):
    """Deposit idle stablecoin into Aave v3 (beta, USDC only).

    Uses on-chain wallet balance (RPC_URL/PRIVATE_KEY) and keeps a configured
    USD reserve in the wallet. In dry-run mode, logs intended actions only.
    """

    if help_verbose:
        typer.echo(
            "Deposits idle wallet USDC to Aave v3. Requires RPC_URL and PRIVATE_KEY.\n"
            "Reserves are computed as max(reserve_amount_usd, reserve_percent * balance_usd).\n"
            "Amounts are in token units: USDC uses 6 decimals. Honors global DRY_RUN."
        )
        raise SystemExit(0)

    asset = (asset or "").strip().upper()
    if asset != "USDC":
        log.error("yield:collect supports USDC only for now")
        return

    try:
        from web3 import Web3  # type: ignore
    except Exception:
        log.error("web3 not installed; cannot perform yield:collect")
        return

    from stake import ERC20_ABI, stake_usdc
    rpc = (getattr(settings, "rpc_url", None) or __import__("os").getenv("RPC_URL"))
    pk = (getattr(settings, "private_key", None) or __import__("os").getenv("PRIVATE_KEY"))
    if not rpc or not pk:
        log.error("RPC_URL and PRIVATE_KEY must be set for yield:collect")
        return

    # Start metrics server if not already running
    try:
        start_metrics_server(settings.prom_port)
    except Exception:
        pass

    w3 = Web3(Web3.HTTPProvider(rpc))
    acct = w3.eth.account.from_key(pk)

    usdc_addr = settings.usdc_address
    usdc = w3.eth.contract(address=usdc_addr, abi=ERC20_ABI)
    bal_raw = int(usdc.functions.balanceOf(acct.address).call())
    # 6 decimals for USDC
    bal_usd = bal_raw / 1_000_000.0

    # Determine reserve
    reserve_abs = (
        float(reserve_usd)
        if reserve_usd is not None
        else float(getattr(settings, "reserve_amount_usd", 0.0))
    )
    reserve_pct = float(getattr(settings, "reserve_percent", 0.0)) / 100.0
    reserve_pct_amt = bal_usd * reserve_pct if reserve_pct > 0 else 0.0
    reserve_final = max(reserve_abs, reserve_pct_amt)

    available_usd = max(bal_usd - reserve_final, 0.0)
    amount_raw = int(available_usd * 1_000_000)
    # Default minimum stake from settings
    min_units = int(min_stake) if min_stake is not None else int(settings.min_usdc_stake)

    if amount_raw < min_units:
        log.info(
            "nothing to do: balance=%.2f USDC reserve=%.2f min_stake=%.2f",
            bal_usd,
            reserve_final,
            min_units / 1_000_000.0,
        )
        return

    if bool(getattr(settings, "dry_run", True)):
        log.info(
            "[dry-run] would deposit %.2f USDC to Aave (reserve=%.2f)",
            amount_raw / 1_000_000.0,
            reserve_final,
        )
        try:
            YIELD_DEPOSITS_TOTAL.labels("aave", "dry_run").inc()
        except Exception:
            pass
        try:
            _notify_discord(
                "yield",
                f"[yield] DRY-RUN deposit {amount_raw/1_000_000.0:.2f} USDC to Aave (reserve={reserve_final:.2f})",
            )
        except Exception:
            pass
        return

    try:
        stake_usdc(amount_raw)
        log.info(
            "deposited %.2f USDC to Aave (kept reserve=%.2f)",
            amount_raw / 1_000_000.0,
            reserve_final,
        )
        try:
            YIELD_DEPOSITS_TOTAL.labels("aave", "live").inc()
        except Exception:
            pass
        try:
            _notify_discord(
                "yield",
                f"[yield] deposited {amount_raw/1_000_000.0:.2f} USDC to Aave (reserve={reserve_final:.2f})",
            )
        except Exception:
            pass
    except Exception as e:  # pragma: no cover - depends on chain state
        log.error("yield:collect deposit error: %s", e)
        try:
            YIELD_ERRORS_TOTAL.labels("deposit").inc()
        except Exception:
            pass


@app.command("yield:withdraw")
@app.command("yield_withdraw")
def yield_withdraw(
    asset: str = "USDC",
    amount_usd: float | None = None,
    all_excess: bool = False,
    reserve_usd: float | None = None,
    help_verbose: bool = False,
):
    """Withdraw USDC from Aave v3 Pool back into the wallet.

    Specify an explicit amount via --amount-usd or use --all-excess to withdraw
    everything above the configured reserve. Honors global DRY_RUN.
    """

    if help_verbose:
        typer.echo(
            "Withdraws USDC from Aave v3. Use --amount-usd for a fixed amount or --all-excess to leave only the reserve."
        )
        raise SystemExit(0)

    asset = (asset or "").strip().upper()
    if asset != "USDC":
        log.error("yield:withdraw supports USDC only for now")
        return

    try:
        from web3 import Web3  # type: ignore
    except Exception:
        log.error("web3 not installed; cannot perform yield:withdraw")
        return

    # Start metrics server if not already running
    try:
        start_metrics_server(settings.prom_port)
    except Exception:
        pass

    from stake import ERC20_ABI, POOL_ABI, withdraw_usdc
    import os as _os

    rpc = (getattr(settings, "rpc_url", None) or _os.getenv("RPC_URL"))
    pk = (getattr(settings, "private_key", None) or _os.getenv("PRIVATE_KEY"))
    if not rpc or not pk:
        log.error("RPC_URL and PRIVATE_KEY must be set for yield:withdraw")
        return

    w3 = Web3(Web3.HTTPProvider(rpc))
    acct = w3.eth.account.from_key(pk)

    # If all_excess, compute based on wallet balance (assumes aToken redemption immediate)
    reserve_abs = (
        float(reserve_usd)
        if reserve_usd is not None
        else float(getattr(settings, "reserve_amount_usd", 0.0))
    )
    reserve_pct = float(getattr(settings, "reserve_percent", 0.0)) / 100.0

    usdc = w3.eth.contract(address=settings.usdc_address, abi=ERC20_ABI)
    bal_raw = int(usdc.functions.balanceOf(acct.address).call())
    bal_usd = bal_raw / 1_000_000.0
    reserve_pct_amt = bal_usd * reserve_pct if reserve_pct > 0 else 0.0
    reserve_final = max(reserve_abs, reserve_pct_amt)

    if amount_usd is None and not all_excess:
        log.error("Specify --amount-usd or --all-excess")
        return

    if all_excess:
        # Withdraw down to reserve, naive approach; a full integration would read aToken balance
        # For now, withdraw the requested difference if wallet < reserve to top up
        if bal_usd >= reserve_final:
            log.info("nothing to do: wallet >= reserve (%.2f >= %.2f)", bal_usd, reserve_final)
            return
        amount_usd = reserve_final - bal_usd

    amount_raw = int(max(float(amount_usd or 0.0), 0.0) * 1_000_000)
    if amount_raw <= 0:
        log.error("withdraw amount must be positive")
        return

    if bool(getattr(settings, "dry_run", True)):
        log.info("[dry-run] would withdraw %.2f USDC from Aave", amount_raw / 1_000_000.0)
        try:
            YIELD_WITHDRAWS_TOTAL.labels("aave", "dry_run").inc()
        except Exception:
            pass
        try:
            _notify_discord(
                "yield",
                f"[yield] DRY-RUN withdraw {amount_raw/1_000_000.0:.2f} USDC from Aave",
            )
        except Exception:
            pass
        return

    try:
        withdraw_usdc(amount_raw)
        log.info("withdrew %.2f USDC from Aave", amount_raw / 1_000_000.0)
        try:
            YIELD_WITHDRAWS_TOTAL.labels("aave", "live").inc()
        except Exception:
            pass
        try:
            _notify_discord(
                "yield", f"[yield] withdrew {amount_raw/1_000_000.0:.2f} USDC from Aave"
            )
        except Exception:
            pass
    except Exception as e:  # pragma: no cover
        log.error("yield:withdraw error: %s", e)
        try:
            YIELD_ERRORS_TOTAL.labels("withdraw").inc()
        except Exception:
            pass


@app.command("yield:watch")
@app.command("yield_watch")
def yield_watch(
    asset: str = "USDC",
    sources: str | None = None,
    interval: float = 60.0,
    apr_hint: float | None = None,
    min_delta_bps: int = 50,
):
    """Periodically fetch APRs and alert if a better yield is found.

    Sources may be a CSV of URLs or a JSON array of URLs. Each URL should
    return a JSON object or list with items like:
    {"provider": "aave", "asset": "USDC", "apr_percent": 3.25}.
    """

    import json as _json
    import urllib.request as _rq
    import os as _os

    def _parse_sources(s: str | None) -> list[str]:
        if not s:
            return []
        s = s.strip()
        try:
            arr = _json.loads(s)
            if isinstance(arr, list):
                return [str(u) for u in arr]
        except Exception:
            pass
        return [u.strip() for u in s.split(",") if u.strip()]

    urls = _parse_sources(sources)
    asset_u = (asset or "").strip().upper() or "USDC"
    target_apr = float(apr_hint) if apr_hint is not None else None
    min_delta = float(min_delta_bps) / 100.0

    log.info(
        "yield:watch asset=%s interval=%.1fs sources=%d min_delta=%.2f%%",
        asset_u,
        interval,
        len(urls),
        min_delta,
    )

    while True:
        try:
            YIELD_CHECKS_TOTAL.inc()
        except Exception:
            pass

        best_apr = 0.0
        best_provider = None
        for url in urls:
            try:
                # Support local files (absolute/relative) and file:// scheme
                data: bytes
                if url.startswith("file://"):
                    path = url[len("file://") :]
                    with open(path, "rb") as fh:
                        data = fh.read()
                elif _os.path.exists(url):
                    with open(url, "rb") as fh:
                        data = fh.read()
                else:
                    with _rq.urlopen(url, timeout=5) as resp:
                        data = resp.read()
                doc = _json.loads(data)
            except Exception:
                continue
            items = doc if isinstance(doc, list) else [doc]
            for it in items:
                try:
                    if (str(it.get("asset", asset_u))).upper() != asset_u:
                        continue
                    provider = str(it.get("provider") or "unknown")
                    apr = float(it.get("apr_percent") or 0.0)
                except Exception:
                    continue
                try:
                    YIELD_APR.labels(provider, asset_u).set(apr)
                except Exception:
                    pass
                if apr > best_apr:
                    best_apr, best_provider = apr, provider

        try:
            YIELD_BEST_APR.labels(asset_u).set(best_apr)
        except Exception:
            pass

        if target_apr is not None and best_apr >= target_apr + min_delta:
            msg = (
                f"Better yield available for {asset_u}: {best_provider} {best_apr:.2f}% "
                f">= current {target_apr:.2f}% + {min_delta:.2f}%"
            )
            log.info(msg)
            try:
                YIELD_ALERTS_TOTAL.labels(asset_u).inc()
            except Exception:
                pass
            _notify_discord("yield", msg)

        time.sleep(max(interval, 1.0))
@app.command("keys:check")
@app.command("keys_check")
def keys_check():
    """Validate exchange credentials by fetching a sample order book."""
    for venue in settings.exchanges:
        try:
            a = _build_adapter(venue, settings)
            ms = a.ex.load_markets()
            symbol = (
                "BTC/USDT"
                if "BTC/USDT" in ms
                else "BTC/USD"
                if "BTC/USD" in ms
                else next(iter(ms))
            )
            ob = a.fetch_orderbook(symbol, 1)
            bid = ob.get("bids", [])
            ask = ob.get("asks", [])
            bid_price = bid[0][0] if bid else "n/a"
            ask_price = ask[0][0] if ask else "n/a"
            log.info(
                "[%s] markets=%d %s %s/%s",
                getattr(a, "name", lambda: a.ex.id)(),
                len(ms),
                symbol,
                bid_price,
                ask_price,
            )
        except Exception as e:
            log.error("[%s] ERROR: %s", venue, e)


@app.command("markets:limits")
@app.command("markets_limits")
def markets_limits(
    venue: str = "alpaca",
    symbols: str | None = None,
):
    """List min-notional (cost.min) and maker/taker fees for symbols.

    Use ``--symbols`` to filter by a comma-separated list, otherwise prints
    entries for the configured triangles for quick relevance.
    """

    a = _build_adapter(venue, settings)
    try:
        ms = a.ex.load_markets()
    except Exception:
        ms = {}

    selected: list[str]
    if symbols:
        selected = [s.strip() for s in symbols.split(",") if s.strip()]
    else:
        tris = _triangles_for(venue)
        selected = sorted({s for t in tris for s in (t.leg_ab, t.leg_bc, t.leg_ac)})

    for s in selected:
        if ms and s not in ms:
            log.info("%s not in markets; skipping", s)
            continue
        try:
            maker, taker = a.fetch_fees(s)
        except Exception:
            maker, taker = 0.0, 0.0
        try:
            min_cost = float(a.min_notional(s))
        except Exception:
            min_cost = 0.0
        log.info(
            "%s min_cost=%.6g maker=%d bps taker=%d bps",
            s,
            min_cost,
            int(round(maker * 1e4)),
            int(round(taker * 1e4)),
        )


@app.command("config:recommend")
@app.command("config_recommend")
def config_recommend(
    venue: str = "alpaca",
):
    """Suggest starter Strategy settings based on current venue data.

    Heuristics:
    - Threshold = (avg taker across legs * 3 + 5 bps) rounded up
    - Notional = max(2 × min_notional(AB), $5)
    - Slippage = 8 bps default
    """

    a = _build_adapter(venue, settings)
    tris = _triangles_for(venue)
    tri = tris[0]
    legs = [tri.leg_ab, tri.leg_bc, tri.leg_ac]
    takers: list[float] = []
    for s in legs:
        try:
            takers.append(a.fetch_fees(s)[1])
        except Exception:
            takers.append(0.001)
    avg_taker = sum(takers) / max(len(takers), 1)
    thresh_bps = int((avg_taker * 3 * 1e4) + 5)  # +5 bps buffer

    try:
        min_cost_ab = float(a.min_notional(tri.leg_ab))
    except Exception:
        min_cost_ab = 1.0
    # Ensure a practical floor for notional suggestion
    notional_usd = max(2.0 * min_cost_ab, 5.0)

    # Recommend defaults
    rec = {
        "NOTIONAL_PER_TRADE_USD": int(round(notional_usd)),
        "NET_THRESHOLD_BPS": max(thresh_bps, 10),
        "MAX_SLIPPAGE_BPS": 8,
        "DRY_RUN": True,
    }
    # Print a compact single-line summary for easy copy/paste
    log.info(
        "Recommend: NOTIONAL_PER_TRADE_USD=%s NET_THRESHOLD_BPS=%s MAX_SLIPPAGE_BPS=%s DRY_RUN=%s",
        rec["NOTIONAL_PER_TRADE_USD"],
        rec["NET_THRESHOLD_BPS"],
        rec["MAX_SLIPPAGE_BPS"],
        str(rec["DRY_RUN"]).lower(),
    )
    # And a bit more context
    log.info(
        "Reference: avg_taker=%d bps legs=%s min_notional_ab=%.6g",
        int(round(avg_taker * 1e4)),
        ",".join(legs),
        min_cost_ab,
    )


@app.command()
def fitness(
    venue: str = "alpaca",
    secs: int = 20,
    simulate: bool = False,
    persist: bool = False,
    dummy_trigger: bool = False,
    help_verbose: bool = False,
):
    """Read-only sanity check that prints bid/ask spreads.

    When ``--simulate`` is provided, attempt dry-run triangle executions using
    current order books and log simulated PnL. Use ``--persist`` to store
    simulated fills in SQLite for later analysis.
    """

    if help_verbose:
        typer.echo(
            "Typical log line: 'kraken ETH/USDT spread=0.5 bps' where spread is the\n"
            "bid/ask gap expressed in basis points (1/100th of a percent)."
        )
        typer.echo(
            "Use --simulate to attempt dry-run triangle executions and log net%/PnL."
        )
        typer.echo(
            "Use --dummy-trigger to inject one synthetic profitable triangle in fitness"
            " mode to exercise the execution path without placing real orders."
        )
        raise SystemExit(0)

    a = _build_adapter(venue, settings)
    tris = _triangles_for(venue)
    t0 = time.time()
    syms = {s for t in tris for s in (t.leg_ab, t.leg_bc, t.leg_ac)}

    # Optional persistence for simulated fills
    conn = None
    if simulate and persist:
        conn = init_db(settings.sqlite_path)
        for tri in tris:
            try:
                insert_triangle(conn, tri)
            except Exception:
                pass

    # Force dry-run behavior during simulation regardless of global setting
    prev_dry_run = settings.dry_run
    if simulate:
        try:
            settings.dry_run = True
        except Exception:
            pass

    sim_count = 0
    sim_pnl = 0.0
    loop_idx = 0
    try:
        while time.time() - t0 < secs:
            books_cache: dict[str, dict] = {}
            # Spread sampling per symbol
            for s in syms:
                ob = a.fetch_orderbook(s, 5)
                books_cache[s] = ob
                if ob.get("bids") and ob.get("asks"):
                    spread = (
                        (ob["asks"][0][0] - ob["bids"][0][0]) / ob["asks"][0][0]
                    ) * 1e4  # bid/ask gap in basis points
                    log.info("%s %s spread=%.1f bps (ask-bid gap)", venue, s, spread)

            # Optional: try triangles in dry-run and log/persist
            if simulate:
                # Optionally inject a synthetic profitable setup once to
                # validate the execution path in fitness mode.
                injected: dict[str, dict] | None = None
                if dummy_trigger and loop_idx == 0 and tris:
                    tri0 = tris[0]
                    # Craft generous top-of-book values that yield a clear edge
                    # with sufficient size to pass min-notional checks.
                    ask_ab = 100.0
                    bid_bc = 1.01
                    bid_ac = 100.7
                    qty = 1.5
                    injected = {
                        tri0.leg_ab: {
                            "bids": [[ask_ab * 0.999, qty]],
                            "asks": [[ask_ab, qty]],
                        },
                        tri0.leg_bc: {
                            "bids": [[bid_bc, qty]],
                            "asks": [[bid_bc * 1.001, qty]],
                        },
                        tri0.leg_ac: {
                            "bids": [[bid_ac, qty]],
                            "asks": [[bid_ac * 1.001, qty]],
                        },
                    }
                    books_cache.update(injected)
                    try:
                        _notify_discord(
                            venue,
                            f"[{venue}] dummy_trigger: injected synthetic profitable triangle for {tri0}",
                        )
                    except Exception:
                        pass

                for tri in tris:
                    skip_reasons: list[str] = []
                    try:
                        t_start = time.time()
                        # If we injected synthetic books for this triangle,
                        # temporarily serve them for top-of-book lookups used
                        # by slippage guards and dry-run fills.
                        if injected and tri.leg_ab in injected:
                            orig_fetch = a.fetch_orderbook

                            def _patched_fetch(sym: str, depth: int = 1):
                                if (
                                    depth == 1 and sym in injected
                                ):  # serve injected top-of-book
                                    # Reduce to 1 level to match depth request
                                    ob = injected[sym]
                                    return {
                                        "bids": [ob["bids"][0]],
                                        "asks": [ob["asks"][0]],
                                    }
                                return orig_fetch(sym, depth)

                            a.fetch_orderbook = _patched_fetch  # type: ignore[assignment]

                        res = try_triangle(
                            a,
                            tri,
                            books_cache,
                            settings.net_threshold_bps / 10000.0,
                            skip_reasons,
                        )
                    except Exception as e:  # defensive: keep fitness resilient
                        log.error("simulate error for %s: %s", tri, e)
                        continue
                    finally:
                        if injected and tri.leg_ab in injected:
                            a.fetch_orderbook = orig_fetch  # type: ignore[assignment]
                    # Persist an attempt record with top-of-book snapshot
                    if conn is not None:

                        def _best(ob, side):
                            try:
                                arr = ob.get(side) or []
                                return arr[0][0] if arr else None
                            except Exception:
                                return None

                        ob_ab = books_cache.get(tri.leg_ab, {})
                        ob_bc = books_cache.get(tri.leg_bc, {})
                        ob_ac = books_cache.get(tri.leg_ac, {})
                        latency_ms = (time.time() - t_start) * 1000.0
                        ok = bool(res)
                        net_est = float(res.get("net_est", 0.0)) if res else None
                        realized = float(res.get("realized_usdt", 0.0)) if res else None
                        qty_base = None
                        if res and res.get("fills"):
                            try:
                                qty_base = float(
                                    res["fills"][0]["qty"]
                                )  # AB leg quantity
                            except Exception:
                                qty_base = None
                        attempt = TriangleAttempt(
                            venue=venue,
                            leg_ab=tri.leg_ab,
                            leg_bc=tri.leg_bc,
                            leg_ac=tri.leg_ac,
                            ts_iso=datetime.now(timezone.utc).isoformat(),
                            ok=ok,
                            net_est=net_est,
                            realized_usdt=realized,
                            threshold_bps=float(
                                getattr(settings, "net_threshold_bps", 0.0)
                            ),
                            notional_usd=float(
                                getattr(settings, "notional_per_trade_usd", 0.0)
                            ),
                            slippage_bps=float(
                                getattr(settings, "max_slippage_bps", 0.0)
                            ),
                            dry_run=True,
                            latency_ms=latency_ms,
                            skip_reasons=(
                                ",".join(skip_reasons) if skip_reasons else None
                            ),
                            ab_bid=_best(ob_ab, "bids"),
                            ab_ask=_best(ob_ab, "asks"),
                            bc_bid=_best(ob_bc, "bids"),
                            bc_ask=_best(ob_bc, "asks"),
                            ac_bid=_best(ob_ac, "bids"),
                            ac_ask=_best(ob_ac, "asks"),
                            qty_base=qty_base,
                        )
                        attempt_id = insert_attempt(conn, attempt)
                    if not res:
                        # Count skips by reason (no metrics emission in fitness)
                        continue
                    sim_count += 1
                    sim_pnl += float(res.get("realized_usdt", 0.0))
                    for f in res.get("fills", []):
                        if conn is not None:
                            try:
                                insert_fill(
                                    conn,
                                    Fill(
                                        order_id=str(f.get("id", "")),
                                        symbol=str(f.get("symbol", "")),
                                        side=str(f.get("side", "")),
                                        price=float(f.get("price", 0.0)),
                                        quantity=float(f.get("qty", 0.0)),
                                        fee=float(f.get("fee", 0.0)),
                                        timestamp=None,
                                        venue=venue,
                                        leg=str(f.get("leg") or ""),
                                        tif=str(f.get("tif") or ""),
                                        order_type=str(f.get("type") or ""),
                                        fee_rate=(
                                            float(f.get("fee_rate"))
                                            if f.get("fee_rate") is not None
                                            else None
                                        ),
                                        notional=float(f.get("price", 0.0))
                                        * float(f.get("qty", 0.0)),
                                        dry_run=True,
                                        attempt_id=(
                                            attempt_id
                                            if "attempt_id" in locals()
                                            else None
                                        ),
                                    ),
                                )
                            except Exception:
                                pass
                    log.info(
                        "%s [sim] %s net=%.3f%% PnL=%.2f USDT",
                        venue,
                        tri,
                        res.get("net_est", 0.0) * 100.0,
                        res.get("realized_usdt", 0.0),
                    )
            time.sleep(0.25)
            loop_idx += 1
    finally:
        if simulate:
            try:
                settings.dry_run = prev_dry_run
            except Exception:
                pass
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

    if simulate:
        log.info(
            "%s [sim] summary: trades=%d total_pnl=%.2f USDT",
            venue,
            sim_count,
            sim_pnl,
        )


@app.command()
def live(
    venue: str = "alpaca",
    help_verbose: bool = False,
):
    """Continuously scan for profitable triangles and execute trades."""

    if help_verbose:
        typer.echo(
            "Log line: 'alpaca Triangle(ETH/USDT, ETH/BTC, BTC/USDT) net=0.15% PnL=0.10 USDT'\n"
            "net = estimated profit after fees; PnL = realized gain in USDT."
        )
        raise SystemExit(0)

    async def _run() -> None:
        a = _build_adapter(venue, settings)
        start_metrics_server(settings.prom_port)
        conn = init_db(settings.sqlite_path)
        tris = _triangles_for(venue)
        for tri in tris:
            insert_triangle(conn, tri)
        log.info("live@%s dry_run=%s", venue, settings.dry_run)
        last_alert_at = 0.0
        last_hb_at = 0.0
        attempts_total = 0
        successes_total = 0
        async for tri, res, skip_reasons, latency in stream_triangles(
            a, tris, settings.net_threshold_bps / 10000.0
        ):
            attempts_total += 1
            try:
                CYCLE_LATENCY.labels(venue).observe(latency)
            except Exception:
                pass
            # Persist attempt record
            try:
                ob_ab = a.fetch_orderbook(tri.leg_ab, 1)
                ob_bc = a.fetch_orderbook(tri.leg_bc, 1)
                ob_ac = a.fetch_orderbook(tri.leg_ac, 1)

                def _best(ob, side):
                    try:
                        arr = ob.get(side) or []
                        return arr[0][0] if arr else None
                    except Exception:
                        return None

                attempt = TriangleAttempt(
                    venue=venue,
                    leg_ab=tri.leg_ab,
                    leg_bc=tri.leg_bc,
                    leg_ac=tri.leg_ac,
                    ts_iso=datetime.now(timezone.utc).isoformat(),
                    ok=bool(res),
                    net_est=(float(res.get("net_est", 0.0)) if res else None),
                    realized_usdt=(
                        float(res.get("realized_usdt", 0.0)) if res else None
                    ),
                    threshold_bps=float(getattr(settings, "net_threshold_bps", 0.0)),
                    notional_usd=float(
                        getattr(settings, "notional_per_trade_usd", 0.0)
                    ),
                    slippage_bps=float(getattr(settings, "max_slippage_bps", 0.0)),
                    dry_run=bool(getattr(settings, "dry_run", True)),
                    latency_ms=latency * 1000.0,
                    skip_reasons=",".join(skip_reasons) if skip_reasons else None,
                    ab_bid=_best(ob_ab, "bids"),
                    ab_ask=_best(ob_ab, "asks"),
                    bc_bid=_best(ob_bc, "bids"),
                    bc_ask=_best(ob_bc, "asks"),
                    ac_bid=_best(ob_ac, "bids"),
                    ac_ask=_best(ob_ac, "asks"),
                    qty_base=(
                        float(res["fills"][0]["qty"])
                        if res and res.get("fills")
                        else None
                    ),
                )
                attempt_id = insert_attempt(conn, attempt)
            except Exception:
                attempt_id = None

            if not res:
                if skip_reasons:
                    for r in skip_reasons:
                        try:
                            SKIPS_TOTAL.labels(venue, r).inc()
                        except Exception:
                            pass
                    actionable = [
                        r
                        for r in skip_reasons
                        if r.startswith("slippage") or r.startswith("min_notional")
                    ]
                    if actionable and time.time() - last_alert_at > 10:
                        _notify_discord(
                            venue,
                            f"[{venue}] skipped {tri} reasons: {', '.join(actionable)}",
                        )
                        last_alert_at = time.time()
                else:
                    try:
                        SKIPS_TOTAL.labels(venue, "unprofitable").inc()
                    except Exception:
                        pass
                continue
            successes_total += 1
            PROFIT_TOTAL.labels(venue).set(res["realized_usdt"])
            ORDERS_TOTAL.labels(venue, "ok").inc()
            for f in res.get("fills", []):
                try:
                    insert_fill(
                        conn,
                        Fill(
                            order_id=str(f.get("id", "")),
                            symbol=str(f.get("symbol", "")),
                            side=str(f.get("side", "")),
                            price=float(f.get("price", 0.0)),
                            quantity=float(f.get("qty", 0.0)),
                            fee=float(f.get("fee", 0.0)),
                            timestamp=None,
                            venue=venue,
                            leg=str(f.get("leg") or ""),
                            tif=str(f.get("tif") or ""),
                            order_type=str(f.get("type") or ""),
                            fee_rate=(
                                float(f.get("fee_rate"))
                                if f.get("fee_rate") is not None
                                else None
                            ),
                            notional=float(f.get("price", 0.0))
                            * float(f.get("qty", 0.0)),
                            dry_run=bool(getattr(settings, "dry_run", True)),
                            attempt_id=attempt_id,
                        ),
                    )
                    FILLS_TOTAL.labels(venue).inc()
                except Exception as e:
                    log.error("persist fill error: %s", e)
            log.info(
                "%s %s net=%.3f%% (est. profit after fees) PnL=%.2f USDT",
                venue,
                tri,
                res["net_est"] * 100,
                res["realized_usdt"],
            )

            # Periodic Discord heartbeat summary
            hb_interval = float(getattr(settings, "discord_heartbeat_secs", 60.0) or 60.0)
            if hb_interval > 0 and time.time() - last_hb_at > hb_interval:
                try:
                    _notify_discord(
                        venue,
                        (
                            f"[{venue}] heartbeat dry_run={getattr(settings, 'dry_run', True)} "
                            f"attempts={attempts_total} successes={successes_total} "
                            f"last_net={res['net_est']*100:.2f}% last_pnl={res['realized_usdt']:.2f} USDT"
                        ),
                    )
                except Exception:
                    pass
                last_hb_at = time.time()

    asyncio.run(_run())


if __name__ == "__main__":
    app()
