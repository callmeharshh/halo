"""First-run setup for your GuardVault on Monad testnet. Safe to re-run.

  python setup_vault.py                 # deposit 1 MON (if low), set limits, approve this app's key, add demo contact
  python setup_vault.py --deposit 2 --max-per-tx 0.5 --daily 2 --trusted-only
"""
import argparse
import sys
from decimal import Decimal

from web3 import Web3

import wallet as wl

DEMO_CONTACT = ("alice", "0x7321B96eC8A116652C4d701371BEa23B6d199b39")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--deposit", type=Decimal, default=Decimal("1"), help="MON to deposit if the vault is below this")
    ap.add_argument("--max-per-tx", type=Decimal, default=Decimal("0.5"))
    ap.add_argument("--daily", type=Decimal, default=Decimal("1"))
    ap.add_argument("--trusted-only", action="store_true", help="only allow payments to saved contacts")
    a = ap.parse_args()

    if wl.vault is None:
        sys.exit("contracts/deployment.json not found.")
    me = wl.address()
    print(f"Wallet:      {me}\nGuardVault:  {wl.VAULT_ADDRESS}\nWallet bal:  {wl.balance():.4f} MON")
    if wl.balance() < Decimal("0.05"):
        sys.exit("Fund this wallet first: https://faucet.monad.xyz")

    have = wl.vault_balance()
    if have < a.deposit:
        top_up = min(a.deposit - have, wl.balance() - Decimal("0.05"))
        if top_up > 0:
            h = wl._vault_tx(wl.vault.functions.deposit(), value=wl.w3.to_wei(top_up, "ether"))
            print(f"Deposited {top_up:.4f} MON -> {wl.explorer_url(h)}")
    to_wei = lambda d: wl.w3.to_wei(d, "ether")
    h = wl._vault_tx(wl.vault.functions.setPolicy(to_wei(a.max_per_tx), to_wei(a.daily), a.trusted_only))
    print(f"Policy set: max {a.max_per_tx}/tx, {a.daily}/day, trusted-only={a.trusted_only} -> {wl.explorer_url(h)}")
    h = wl._vault_tx(wl.vault.functions.setAgent(me))
    print(f"Agent key approved -> {wl.explorer_url(h)}")
    name, addr = DEMO_CONTACT
    print(wl.add_contact(name, addr))
    print(f"\nVault balance: {wl.vault_balance():.4f} MON. Ready: python main.py")


if __name__ == "__main__":
    main()
