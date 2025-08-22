from web3 import Web3
import json, os

RPC = os.getenv("RPC_URL")  # e.g., Infura/Alchemy
w3 = Web3(
    Web3.HTTPProvider(RPC)
)  # needs a node provider connection :contentReference[oaicite:6]{index=6}
acct = w3.eth.account.from_key(os.getenv("PRIVATE_KEY"))

# You’ll need:
# - USDC ERC20 contract (approve)
# - Aave v3 Pool contract (supply)
# Fetch addresses/ABIs from Aave docs / deployment registry for your chain. :contentReference[oaicite:7]{index=7}

USDC = w3.eth.contract(address=..., abi=json.load(open("erc20.json")))
POOL = w3.eth.contract(address=..., abi=json.load(open("aave_pool.json")))

amount = 1_000 * 10**6  # 1000 USDC (6 decimals)

# 1) Approve
tx1 = USDC.functions.approve(POOL.address, amount).build_transaction({...})
signed1 = acct.sign_transaction(tx1)
w3.eth.send_raw_transaction(signed1.rawTransaction)

# 2) Supply (Aave v3 Pool.supply(asset, amount, onBehalfOf, referralCode))
tx2 = POOL.functions.supply(USDC.address, amount, acct.address, 0).build_transaction(
    {...}
)
signed2 = acct.sign_transaction(tx2)
w3.eth.send_raw_transaction(signed2.rawTransaction)
