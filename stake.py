"""Stake USDC into Aave v3 using configured contract data.

This module demonstrates approving USDC for spending by the Aave v3 Pool
contract and then supplying it to the pool. Contract addresses and ABI file
paths are loaded from :class:`arbit.config.Settings`.

Usage:
    Export ``RPC_URL``, ``PRIVATE_KEY`` and the necessary ``ARBIT_`` settings
    before running the module.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from web3 import Web3

from arbit.config import Settings


def stake_usdc(amount: int) -> None:
    """Approve and deposit ``amount`` of USDC into Aave v3.

    Args:
        amount: USDC amount in base units (6 decimals) to supply.
    """

    settings = Settings()

    w3 = Web3(Web3.HTTPProvider(os.getenv("RPC_URL")))
    acct = w3.eth.account.from_key(os.getenv("PRIVATE_KEY"))

    usdc_abi = json.loads(Path(settings.usdc_abi_path).read_text())
    pool_abi = json.loads(Path(settings.pool_abi_path).read_text())

    usdc = w3.eth.contract(address=settings.usdc_address, abi=usdc_abi)
    pool = w3.eth.contract(address=settings.pool_address, abi=pool_abi)

    tx1 = usdc.functions.approve(pool.address, amount).build_transaction({...})
    signed1 = acct.sign_transaction(tx1)
    w3.eth.send_raw_transaction(signed1.rawTransaction)

    tx2 = pool.functions.supply(
        usdc.address, amount, acct.address, 0
    ).build_transaction({
        ...
    })
    signed2 = acct.sign_transaction(tx2)
    w3.eth.send_raw_transaction(signed2.rawTransaction)


if __name__ == "__main__":
    AMOUNT = 1_000 * 10**6  # 1000 USDC (6 decimals)
    stake_usdc(AMOUNT)

