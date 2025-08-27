"""Tests for staking helper functions."""

import pytest

from stake import ensure_account_ready


class DummyCall:
    def __init__(self, value: int) -> None:
        self._value = value

    def call(self) -> int:  # pragma: no cover - trivial
        return self._value


class DummyToken:
    def __init__(self, balance: int) -> None:
        self._balance = balance
        self.functions = self

    def balanceOf(self, _addr: str) -> DummyCall:  # pragma: no cover - simple
        return DummyCall(self._balance)


class DummyEth:
    def __init__(self, balance: int) -> None:
        self._balance = balance

    def get_balance(self, _addr: str) -> int:  # pragma: no cover - trivial
        return self._balance


class DummyW3:
    def __init__(self, balance: int) -> None:
        self.eth = DummyEth(balance)


class DummyAccount:
    def __init__(self, address: str) -> None:
        self.address = address


def test_account_ready() -> None:
    """No error when balances meet the requirements."""

    w3 = DummyW3(balance=10**18)
    token = DummyToken(balance=1_000)
    acct = DummyAccount("0xabc")
    ensure_account_ready(w3, acct, token, amount=100, min_token=100, min_eth=10**17)


def test_insufficient_token_raises() -> None:
    """A low USDC balance raises a ``ValueError``."""

    w3 = DummyW3(balance=10**18)
    token = DummyToken(balance=50)
    acct = DummyAccount("0xabc")
    with pytest.raises(ValueError):
        ensure_account_ready(w3, acct, token, amount=100, min_token=100, min_eth=10**17)


def test_insufficient_eth_raises() -> None:
    """A low ETH balance raises a ``ValueError``."""

    w3 = DummyW3(balance=10**16)
    token = DummyToken(balance=1_000)
    acct = DummyAccount("0xabc")
    with pytest.raises(ValueError):
        ensure_account_ready(w3, acct, token, amount=100, min_token=100, min_eth=10**17)

