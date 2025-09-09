"""Yield provider interface and Aave v3 implementation.

This module abstracts deposit/withdraw and balance reads for yield providers
so CLI commands can remain provider-agnostic and we can extend to other
providers in future.
"""

from __future__ import annotations

from typing import Optional


class YieldProvider:
    """Abstract provider interface."""

    def get_wallet_balance_raw(self) -> int:
        """Return wallet token balance in smallest units (e.g., 6-decimal USDC)."""

        raise NotImplementedError

    def get_deposit_balance_raw(self) -> int:
        """Return interest-bearing token balance (e.g., aToken) in raw units.

        Should return 0 when not available or not applicable.
        """

        raise NotImplementedError

    def deposit_raw(self, amount: int) -> None:
        """Execute a deposit of ``amount`` raw units."""

        raise NotImplementedError

    def withdraw_raw(self, amount: int) -> None:
        """Execute a withdrawal of ``amount`` raw units."""

        raise NotImplementedError


class AaveProvider(YieldProvider):
    """Aave v3 provider backed by web3 and stake.py helpers.

    Reads balances directly via ERC20 and aToken contracts. Submits deposits
    and withdrawals using the existing :mod:`stake` module to leverage its
    safety checks.
    """

    def __init__(self, settings, w3: Optional[object] = None, acct: Optional[object] = None):
        self.settings = settings
        self._w3 = None
        self._acct = None
        self._usdc = None
        self._atoken = None

        # Lazy import to avoid hard requiring web3 unless used.
        from stake import ERC20_ABI  # type: ignore

        try:
            if w3 is None or acct is None:
                from web3 import Web3  # type: ignore

                rpc = getattr(settings, "rpc_url", None) or __import__("os").getenv("RPC_URL")
                pk = getattr(settings, "private_key", None) or __import__("os").getenv("PRIVATE_KEY")
                if not rpc or not pk:
                    # Defer failure to method use; allow dry-run paths to proceed.
                    return
                w3 = Web3(Web3.HTTPProvider(rpc))
                acct = w3.eth.account.from_key(pk)
            self._w3 = w3
            self._acct = acct
            self._usdc = self._w3.eth.contract(address=settings.usdc_address, abi=ERC20_ABI)
            atok_addr = getattr(settings, "atoken_address", None)
            if atok_addr:
                self._atoken = self._w3.eth.contract(address=atok_addr, abi=ERC20_ABI)
        except Exception:
            # Keep provider usable for dry-run logs even if web3 not ready.
            self._w3 = None
            self._acct = None
            self._usdc = None
            self._atoken = None

    def get_wallet_balance_raw(self) -> int:  # pragma: no cover - trivial wrapper
        if not (self._w3 and self._acct and self._usdc):
            return 0
        return int(self._usdc.functions.balanceOf(self._acct.address).call())

    def get_deposit_balance_raw(self) -> int:  # pragma: no cover - trivial wrapper
        if not (self._w3 and self._acct and self._atoken):
            return 0
        try:
            return int(self._atoken.functions.balanceOf(self._acct.address).call())
        except Exception:
            return 0

    def deposit_raw(self, amount: int) -> None:
        from stake import stake_usdc  # type: ignore

        stake_usdc(int(amount))

    def withdraw_raw(self, amount: int) -> None:
        from stake import withdraw_usdc  # type: ignore

        withdraw_usdc(int(amount))

