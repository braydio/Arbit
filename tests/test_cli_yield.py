"""CLI tests for yield commands using a mocked provider.

Uses Typer's CliRunner and a temporary SQLite file for persistence checks.
"""

import sqlite3
import sys
from types import SimpleNamespace

from arbit import config as cfg
from typer.testing import CliRunner


class DummyProvider:
    def __init__(self, wallet_raw: int, atoken_raw: int):
        self._wallet = wallet_raw
        self._atoken = atoken_raw
        self.deposits = []
        self.withdrawals = []

    def get_wallet_balance_raw(self) -> int:
        return self._wallet

    def get_deposit_balance_raw(self) -> int:
        return self._atoken

    def deposit_raw(self, amount: int) -> None:
        self.deposits.append(int(amount))

    def withdraw_raw(self, amount: int) -> None:
        self.withdrawals.append(int(amount))


def test_yield_collect_dry_run_persists_op(monkeypatch, tmp_path):
    # Configure settings to use a temp DB and dry_run
    cfg.settings.sqlite_path = str(tmp_path / "test.db")
    cfg.settings.dry_run = True
    # Wallet: 300 USDC, aToken: 0
    monkeypatch.setattr(
        "arbit.cli.AaveProvider", lambda *_args, **_kw: DummyProvider(300_000_000, 0)
    )

    # Provide a dummy ccxt in sys.modules prior to importing arbit.cli
    sys.modules.setdefault("ccxt", SimpleNamespace())
    from arbit.cli import app as cli_app  # import after stubbing ccxt

    runner = CliRunner()
    res = runner.invoke(
        cli_app, ["yield:collect", "--reserve-usd", "50"]
    )  # deposit 250
    assert res.exit_code == 0

    # Verify yield_ops row written
    con = sqlite3.connect(cfg.settings.sqlite_path)
    cur = con.cursor()
    cur.execute("SELECT provider, op, amount_raw, mode FROM yield_ops")
    rows = cur.fetchall()
    assert rows, res.output
    # Expect dry_run deposit of 250 USDC in raw units
    provider, op, amount_raw, mode = rows[-1]
    assert provider == "aave" and op == "deposit" and mode == "dry_run"
    assert amount_raw == 250_000_000


def test_yield_withdraw_all_excess_dry_run_persists(monkeypatch, tmp_path):
    cfg.settings.sqlite_path = str(tmp_path / "test.db")
    cfg.settings.dry_run = True
    # Wallet: 10 USDC, aToken: 200 USDC
    monkeypatch.setattr(
        "arbit.cli.AaveProvider",
        lambda *_args, **_kw: DummyProvider(10_000_000, 200_000_000),
    )

    sys.modules.setdefault("ccxt", SimpleNamespace())
    from arbit.cli import app as cli_app

    runner = CliRunner()
    res = runner.invoke(
        cli_app, ["yield:withdraw", "--all-excess", "--reserve-usd", "50"]
    )
    assert res.exit_code == 0

    # Verify yield_ops row
    con = sqlite3.connect(cfg.settings.sqlite_path)
    cur = con.cursor()
    cur.execute("SELECT provider, op, amount_raw, mode FROM yield_ops")
    rows = cur.fetchall()
    assert rows, res.output
    provider, op, amount_raw, mode = rows[-1]
    assert provider == "aave" and op == "withdraw" and mode == "dry_run"
    # Target top-up = 40 USDC (50-10), capped by aToken (200) -> 40 USDC
    assert amount_raw == 40_000_000
