"""Tests for the Aave staking helper module."""

from __future__ import annotations

import logging
import types

import stake


def patch_settings(monkeypatch, *, dry_run: bool) -> None:
    """Override :func:`stake._load_settings` with a deterministic stub."""

    monkeypatch.setattr(stake, "_load_settings", lambda: DummySettings(dry_run=dry_run))


class DummySettings:
    """Minimal settings stub for staking tests."""

    def __init__(self, *, dry_run: bool):
        self.dry_run = dry_run
        self.usdc_address = "0xusdc"
        self.pool_address = "0xpool"
        self.min_usdc_stake = 1
        self.min_eth_balance_wei = 1
        self.max_gas_price_gwei = 5


class DummyTokenFunctions:
    """Emulate ERC20 contract functions used by :mod:`stake`."""

    def __init__(self, token: "DummyToken") -> None:
        self._token = token

    def balanceOf(self, _owner: str):  # noqa: N802 - mimic Web3 naming
        return types.SimpleNamespace(call=lambda: self._token.balance)

    def approve(self, spender: str, value: int):  # noqa: N802
        self._token.approve_args.append((spender, value))
        return types.SimpleNamespace(
            build_transaction=lambda params: {**params, "kind": "approve"}
        )


class DummyToken:
    """ERC20 token stub capturing approve calls."""

    def __init__(self, balance: int) -> None:
        self.address = "0xusdc"
        self.balance = balance
        self.approve_args: list[tuple[str, int]] = []
        self.functions = DummyTokenFunctions(self)


class DummyPoolFunctions:
    """Simulate the subset of pool contract methods we invoke."""

    def __init__(self, pool: "DummyPool") -> None:
        self._pool = pool

    def supply(self, asset: str, amount: int, on_behalf: str, referral: int):  # noqa: N802
        self._pool.supply_args.append((asset, amount, on_behalf, referral))
        return types.SimpleNamespace(
            build_transaction=lambda params: {**params, "kind": "supply"}
        )

    def withdraw(self, asset: str, amount: int, to: str):  # noqa: N802
        self._pool.withdraw_args.append((asset, amount, to))
        return types.SimpleNamespace(
            build_transaction=lambda params: {**params, "kind": "withdraw"}
        )


class DummyPool:
    """Aave pool contract stub tracking supply/withdraw invocations."""

    def __init__(self) -> None:
        self.address = "0xpool"
        self.supply_args: list[tuple[str, int, str, int]] = []
        self.withdraw_args: list[tuple[str, int, str]] = []
        self.functions = DummyPoolFunctions(self)


class DummyEth:
    """Minimal Web3 ``eth`` namespace used in staking routines."""

    def __init__(self, sent: list[str]) -> None:
        self._sent = sent
        self.gas_price = 2 * 10**9

    def get_balance(self, _address: str) -> int:  # pragma: no cover - trivial
        return 10**18

    def get_transaction_count(self, _address: str) -> int:
        return len(self._sent)

    def send_raw_transaction(self, raw: str) -> None:
        self._sent.append(raw)


class DummyWeb3:
    """Container providing the ``eth`` namespace for staking tests."""

    def __init__(self, sent: list[str]) -> None:
        self.eth = DummyEth(sent)


class DummyAccount:
    """Account stub returning deterministic signatures."""

    address = "0xacct"

    def sign_transaction(self, tx: dict) -> types.SimpleNamespace:
        return types.SimpleNamespace(rawTransaction=f"signed-{tx['nonce']}-{tx['kind']}")


def test_stake_usdc_dry_run_skips_web3(monkeypatch, caplog):
    """Dry-run mode should avoid initialising Web3 clients."""

    patch_settings(monkeypatch, dry_run=True)

    called = False

    def fake_init(settings):  # pragma: no cover - executed when test fails
        nonlocal called
        called = True
        return stake._init_web3_clients(settings)

    monkeypatch.setattr(stake, "_init_web3_clients", fake_init)

    with caplog.at_level(logging.INFO):
        stake.stake_usdc(1_500_000)

    assert called is False
    assert "[dry-run]" in caplog.text


def test_stake_usdc_live_executes_transactions(monkeypatch):
    """Live staking should submit approve and supply transactions."""

    patch_settings(monkeypatch, dry_run=False)

    sent: list[str] = []
    token = DummyToken(balance=2_000_000)
    pool = DummyPool()
    account = DummyAccount()

    def fake_init(_settings):
        return DummyWeb3(sent), account, token, pool

    monkeypatch.setattr(stake, "_init_web3_clients", fake_init)

    stake.stake_usdc(1_000_000)

    assert sent == ["signed-0-approve", "signed-1-supply"]
    assert token.approve_args == [(pool.address, 1_000_000)]
    assert pool.supply_args == [(token.address, 1_000_000, account.address, 0)]


def test_withdraw_usdc_respects_dry_run(monkeypatch, caplog):
    """Dry-run withdraw should bypass Web3 initialisation."""

    patch_settings(monkeypatch, dry_run=True)

    invoked = False

    def fake_init(settings):  # pragma: no cover - executed when dry-run fails
        nonlocal invoked
        invoked = True
        return stake._init_web3_clients(settings)

    monkeypatch.setattr(stake, "_init_web3_clients", fake_init)

    with caplog.at_level(logging.INFO):
        stake.withdraw_usdc(500_000)

    assert invoked is False
    assert "[dry-run]" in caplog.text


def test_withdraw_usdc_live_executes_transaction(monkeypatch):
    """Live withdraw should submit a single transaction."""

    patch_settings(monkeypatch, dry_run=False)

    sent: list[str] = []
    token = DummyToken(balance=2_000_000)
    pool = DummyPool()
    account = DummyAccount()

    def fake_init(_settings):
        return DummyWeb3(sent), account, token, pool

    monkeypatch.setattr(stake, "_init_web3_clients", fake_init)

    stake.withdraw_usdc(750_000)

    assert sent == ["signed-0-withdraw"]
    assert pool.withdraw_args == [(token.address, 750_000, account.address)]
