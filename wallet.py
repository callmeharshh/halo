"""Monad testnet wallet layer. Pure functions, no LLM, no UI."""
import json
import os
import re
from decimal import Decimal, InvalidOperation

from dotenv import load_dotenv
from web3 import Web3
from eth_account import Account

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

RPC = os.getenv("MONAD_RPC", "https://testnet-rpc.monad.xyz")
CHAIN_ID = int(os.getenv("MONAD_CHAIN_ID", "10143"))
EXPLORER = "https://testnet.monadexplorer.com"
CONTACTS_PATH = os.path.join(BASE_DIR, "contacts.json")
MAX_SEND = Decimal(os.getenv("MAX_SEND_MON", "1"))  # hard safety cap per transfer

w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 15}))
_acct = Account.from_key(os.environ["WALLET_PRIVATE_KEY"]) if os.getenv("WALLET_PRIVATE_KEY") else None

DEFAULT_CONTACTS = {
    # Demo contacts. Edit contacts.json (or say "add contact ...") to change.
    "alice": "0x7321B96eC8A116652C4d701371BEa23B6d199b39",
}


class WalletError(Exception):
    pass


# ── contacts ────────────────────────────────────────────────────────────────
def load_contacts() -> dict:
    if not os.path.exists(CONTACTS_PATH):
        save_contacts(DEFAULT_CONTACTS)
        return dict(DEFAULT_CONTACTS)
    with open(CONTACTS_PATH) as f:
        return json.load(f)


def save_contacts(c: dict):
    with open(CONTACTS_PATH, "w") as f:
        json.dump(c, f, indent=2)


def add_contact(name: str, address: str) -> str:
    if not Web3.is_address(address):
        raise WalletError(f"'{address}' is not a valid address.")
    c = load_contacts()
    c[name.strip().lower()] = Web3.to_checksum_address(address)
    save_contacts(c)
    return f"Saved contact {name}."


def resolve_recipient(who: str) -> tuple[str, str]:
    """Return (label, checksum address) for a contact name or 0x address."""
    who = who.strip()
    if Web3.is_address(who):
        addr = Web3.to_checksum_address(who)
        return addr[:6] + "…" + addr[-4:], addr
    c = load_contacts()
    key = re.sub(r"[^a-z0-9 ]", "", who.lower()).strip()
    if key in c:
        return key.title(), Web3.to_checksum_address(c[key])
    raise WalletError(f"I don't have a contact named '{who}'.")


# ── reads ───────────────────────────────────────────────────────────────────
def address() -> str:
    if not _acct:
        raise WalletError("No wallet configured.")
    return _acct.address


def balance(addr: str | None = None) -> Decimal:
    a = Web3.to_checksum_address(addr or address())
    return Decimal(w3.from_wei(w3.eth.get_balance(a), "ether"))


def tx_status(tx_hash: str) -> str:
    try:
        r = w3.eth.get_transaction_receipt(tx_hash)
        return "confirmed" if r.status == 1 else "failed"
    except Exception:
        return "pending"


def explorer_url(tx_hash: str) -> str:
    return f"{EXPLORER}/tx/{tx_hash}"


# ── writes ──────────────────────────────────────────────────────────────────
def parse_amount(amount) -> Decimal:
    try:
        d = Decimal(str(amount))
    except InvalidOperation:
        raise WalletError(f"'{amount}' is not a valid amount.")
    if d <= 0:
        raise WalletError("Amount must be positive.")
    if d > MAX_SEND:
        raise WalletError(f"Amount exceeds the safety limit of {MAX_SEND} MON per transfer.")
    return d


def prepare_transfer(to: str, amount) -> dict:
    """Validate everything and return a summary. Does NOT send."""
    label, addr = resolve_recipient(to)
    amt = parse_amount(amount)
    bal = balance()
    if bal < amt + Decimal("0.01"):
        raise WalletError(f"Insufficient balance: {bal:.4f} MON available.")
    return {"label": label, "to": addr, "amount": amt}


def send_mon(to_addr: str, amount: Decimal, wait: bool = True) -> str:
    """Sign and broadcast. Callers MUST have obtained confirmation first."""
    if not _acct:
        raise WalletError("No wallet configured.")
    tx = {
        "to": Web3.to_checksum_address(to_addr),
        "value": w3.to_wei(amount, "ether"),
        "nonce": w3.eth.get_transaction_count(_acct.address),
        "chainId": CHAIN_ID,
        "gas": 21000,
        "gasPrice": w3.eth.gas_price,
    }
    signed = _acct.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction).hex()
    if not tx_hash.startswith("0x"):
        tx_hash = "0x" + tx_hash
    if wait:
        w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
    return tx_hash
