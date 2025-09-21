"""Stake USDC into Aave v3 with balance and fee checks.

This module approves and deposits USDC into the Aave v3 pool on
Arbitrum.  It loads default contract addresses and thresholds from
``arbit.config.Settings`` to minimise setup.  Before submitting any
transactions the account's ETH and USDC balances are verified and the
current gas price is checked against a configurable ceiling.

Usage:
    Export ``RPC_URL`` and ``PRIVATE_KEY`` before running the module.
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger(__name__)

# Minimal ABIs for the functions we invoke.  Keeping these inline avoids the
# need to distribute separate JSON artefacts.
ERC20_ABI = [
    {
        "name": "approve",
        "type": "function",
        "inputs": [
            {"name": "_spender", "type": "address"},
            {"name": "_value", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "name": "balanceOf",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "_owner", "type": "address"}],
        "outputs": [{"name": "balance", "type": "uint256"}],
    },
]

POOL_ABI = [
    {
        "name": "supply",
        "type": "function",
        "inputs": [
            {"name": "asset", "type": "address"},
            {"name": "amount", "type": "uint256"},
            {"name": "onBehalfOf", "type": "address"},
            {"name": "referralCode", "type": "uint16"},
        ],
        "outputs": [],
    },
    {
        "name": "withdraw",
        "type": "function",
        "inputs": [
            {"name": "asset", "type": "address"},
            {"name": "amount", "type": "uint256"},
            {"name": "to", "type": "address"},
        ],
        "outputs": [{"name": "amountWithdrawn", "type": "uint256"}],
    },
]


def _init_web3_clients(settings: Any) -> tuple[Any, Any, Any, Any]:
    """Return Web3 helpers initialised with configured contract addresses."""

    rpc_url = os.getenv("RPC_URL")
    private_key = os.getenv("PRIVATE_KEY")
    if not rpc_url or not private_key:
        raise EnvironmentError("RPC_URL and PRIVATE_KEY must be configured")

    from web3 import Web3

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    acct = w3.eth.account.from_key(private_key)
    usdc = w3.eth.contract(address=settings.usdc_address, abi=ERC20_ABI)
    pool = w3.eth.contract(address=settings.pool_address, abi=POOL_ABI)
    return w3, acct, usdc, pool


def _load_settings() -> Any:
    """Return a configured :class:`arbit.config.Settings` instance."""

    from arbit.config import Settings

    return Settings()


def ensure_account_ready(
    w3: Any,
    acct: Any,
    token: Any,
    amount: int,
    *,
    min_token: int,
    min_eth: int,
) -> None:
    """Validate that *acct* holds enough USDC and ETH for staking.

    Raises:
        ValueError: If balances are below the required minimums.
    """

    token_balance = token.functions.balanceOf(acct.address).call()
    if token_balance < max(amount, min_token):
        raise ValueError("USDC balance below required minimum")

    eth_balance = w3.eth.get_balance(acct.address)
    if eth_balance < min_eth:
        raise ValueError("ETH balance below required minimum for gas")


def stake_usdc(amount: int) -> None:
    """Approve and deposit ``amount`` of USDC into Aave v3."""

    settings = _load_settings()

    if bool(getattr(settings, "dry_run", True)):
        log.info(
            "[dry-run] would stake %.2f USDC to Aave",
            float(amount) / 1_000_000.0,
        )
        return

    w3, acct, usdc, pool = _init_web3_clients(settings)

    ensure_account_ready(
        w3,
        acct,
        usdc,
        amount,
        min_token=settings.min_usdc_stake,
        min_eth=settings.min_eth_balance_wei,
    )

    gas_price = w3.eth.gas_price
    if gas_price > settings.max_gas_price_gwei * 10**9:
        raise RuntimeError("Gas price exceeds configured maximum")

    nonce = w3.eth.get_transaction_count(acct.address)

    tx1 = usdc.functions.approve(pool.address, amount).build_transaction(
        {"from": acct.address, "nonce": nonce, "gasPrice": gas_price}
    )
    signed1 = acct.sign_transaction(tx1)
    w3.eth.send_raw_transaction(signed1.rawTransaction)

    nonce += 1
    tx2 = pool.functions.supply(
        usdc.address, amount, acct.address, 0
    ).build_transaction({"from": acct.address, "nonce": nonce, "gasPrice": gas_price})
    signed2 = acct.sign_transaction(tx2)
    w3.eth.send_raw_transaction(signed2.rawTransaction)


def withdraw_usdc(amount: int) -> None:
    """Withdraw ``amount`` of USDC from Aave v3 Pool to the wallet."""

    settings = _load_settings()

    if bool(getattr(settings, "dry_run", True)):
        log.info(
            "[dry-run] would withdraw %.2f USDC from Aave",
            float(amount) / 1_000_000.0,
        )
        return

    w3, acct, usdc, pool = _init_web3_clients(settings)

    gas_price = w3.eth.gas_price
    if gas_price > settings.max_gas_price_gwei * 10**9:
        raise RuntimeError("Gas price exceeds configured maximum")

    nonce = w3.eth.get_transaction_count(acct.address)

    tx = pool.functions.withdraw(usdc.address, amount, acct.address).build_transaction(
        {"from": acct.address, "nonce": nonce, "gasPrice": gas_price}
    )
    signed = acct.sign_transaction(tx)
    w3.eth.send_raw_transaction(signed.rawTransaction)


if __name__ == "__main__":
    from arbit.config import Settings

    AMOUNT = Settings().min_usdc_stake
    stake_usdc(AMOUNT)
