"""Compile GuardVault and deploy it to Monad testnet. Writes contracts/deployment.json.

Usage:  python contracts/deploy.py            (uses WALLET_PRIVATE_KEY and MONAD_RPC from .env)
"""
import json
import os
import sys

import solcx
from dotenv import load_dotenv
from web3 import Web3

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
load_dotenv(os.path.join(ROOT, ".env"))

SOLC = "0.8.26"
CONTRACT_NAME = sys.argv[1] if len(sys.argv) > 1 else "GuardVault"
SRC_NAME = f"contracts/{CONTRACT_NAME}.sol"


def compile_contract():
    solcx.install_solc(SOLC)
    source = open(os.path.join(HERE, f"{CONTRACT_NAME}.sol")).read()
    std_input = {
        "language": "Solidity",
        "sources": {SRC_NAME: {"content": source}},
        "settings": {
            "optimizer": {"enabled": True, "runs": 200},
            "evmVersion": "cancun",
            "metadata": {"bytecodeHash": "none", "useLiteralContent": True},
            "outputSelection": {"*": {"*": ["abi", "evm.bytecode.object", "metadata"]}},
        },
    }
    out = solcx.compile_standard(std_input, solc_version=SOLC)
    c = out["contracts"][SRC_NAME][CONTRACT_NAME]
    return std_input, c["abi"], "0x" + c["evm"]["bytecode"]["object"]


def main():
    std_input, abi, bytecode = compile_contract()
    w3 = Web3(Web3.HTTPProvider(os.getenv("MONAD_RPC", "https://testnet-rpc.monad.xyz")))
    acct = w3.eth.account.from_key(os.environ["WALLET_PRIVATE_KEY"])
    print("deployer:", acct.address, "balance:", w3.from_wei(w3.eth.get_balance(acct.address), "ether"), "MON")
    contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx = contract.constructor().build_transaction({
        "from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address),
        "chainId": int(os.getenv("MONAD_CHAIN_ID", "10143")), "gasPrice": w3.eth.gas_price,
    })
    tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.3)
    signed = acct.sign_transaction(tx)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    print("deploy tx:", h.hex())
    r = w3.eth.wait_for_transaction_receipt(h, timeout=90)
    assert r.status == 1, "deployment failed"
    print(f"{CONTRACT_NAME} deployed at:", r.contractAddress, "block", r.blockNumber)
    json.dump({
        "contract": CONTRACT_NAME, "address": r.contractAddress, "chainId": 10143, "network": "Monad Testnet",
        "deployTx": "0x" + h.hex().removeprefix("0x"), "deployer": acct.address, "block": r.blockNumber,
        "solc": SOLC, "abi": abi, "standardInput": std_input,
    }, open(os.path.join(HERE, "deployment.json" if CONTRACT_NAME == "GuardVault" else f"deployment.{CONTRACT_NAME}.json"), "w"), indent=2)


if __name__ == "__main__":
    sys.exit(main())
