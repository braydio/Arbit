"""Tests for yield provider abstraction (AaveProvider).

These tests focus on balance-reading helpers with injected dummy web3.
"""

import importlib
from types import SimpleNamespace

# Import provider via importlib because `yield` is a Python keyword
AaveProvider = importlib.import_module("arbit.yield.providers").AaveProvider


class DummyCall:
    def __init__(self, value: int) -> None:
        self._value = value

    def call(self) -> int:
        return self._value


class DummyToken:
    def __init__(self, balance: int) -> None:
        self._balance = balance
        self.functions = self

    def balanceOf(self, _addr: str):  # noqa: N802 - mimic solidity name
        return DummyCall(self._balance)


class DummyEth:
    def __init__(self) -> None:
        pass


class DummyW3:
    def __init__(self) -> None:
        self.eth = SimpleNamespace()

    def HTTPProvider(self, *_args, **_kwargs):  # pragma: no cover - compatibility
        return self

    def contract(self, *, address, abi):  # noqa: D401
        # Return USDC or aToken dummy by address tag in tests
        if address == "USDC":
            return DummyToken(1_500_000)  # 1.5 USDC
        if address == "aUSDC":
            return DummyToken(3_000_000)  # 3.0 aUSDC
        return DummyToken(0)


def test_provider_balance_reads_with_atoken(monkeypatch):
    settings = SimpleNamespace(usdc_address="USDC", atoken_address="aUSDC")
    # Inject dummy w3 and account
    acct = SimpleNamespace(address="0xabc")
    w3 = SimpleNamespace(eth=SimpleNamespace(contract=DummyW3().contract))
    p = AaveProvider(settings, w3=w3, acct=acct)

    assert p.get_wallet_balance_raw() == 1_500_000
    assert p.get_deposit_balance_raw() == 3_000_000


def test_provider_balance_reads_without_atoken():
    settings = SimpleNamespace(usdc_address="USDC", atoken_address=None)
    acct = SimpleNamespace(address="0xabc")
    w3 = SimpleNamespace(eth=SimpleNamespace(contract=DummyW3().contract))
    p = AaveProvider(settings, w3=w3, acct=acct)

    assert p.get_wallet_balance_raw() == 1_500_000
    assert p.get_deposit_balance_raw() == 0
