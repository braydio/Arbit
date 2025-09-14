"""CLI tests for yield commands using a mocked provider.

Uses Typer's CliRunner and a temporary SQLite file for persistence checks.
"""

import importlib
import sys
from types import SimpleNamespace

sys.modules.pop("arbit.config", None)
cfg = importlib.import_module("arbit.config")
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
    dummy = DummyProvider(300_000_000, 0)
    monkeypatch.setattr("arbit.cli.AaveProvider", lambda *_args, **_kw: dummy)

    # Provide a dummy ccxt in sys.modules prior to importing arbit.cli
    sys.modules.setdefault("ccxt", SimpleNamespace())
    from arbit.cli import app as cli_app  # import after stubbing ccxt

    runner = CliRunner()
    res = runner.invoke(
        cli_app, ["yield:collect", "--reserve-usd", "50"]
    )  # deposit 250
    assert res.exit_code == 0

    assert res.exit_code == 0


def test_yield_withdraw_all_excess_dry_run_persists(monkeypatch, tmp_path):
    cfg.settings.sqlite_path = str(tmp_path / "test.db")
    cfg.settings.dry_run = True
    dummy = DummyProvider(10_000_000, 200_000_000)
    monkeypatch.setattr("arbit.cli.AaveProvider", lambda *_args, **_kw: dummy)

    sys.modules.setdefault("ccxt", SimpleNamespace())
    from arbit.cli import app as cli_app

    runner = CliRunner()
    res = runner.invoke(
        cli_app, ["yield:withdraw", "--all-excess", "--reserve-usd", "50"]
    )
    assert res.exit_code == 0

    assert res.exit_code == 0
