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
EXPLORER = "https://testnet.monadscan.com"
CONTACTS_PATH = os.path.join(BASE_DIR, "contacts.json")
MAX_SEND = Decimal(os.getenv("MAX_SEND_MON", "1"))  # hard safety cap per transfer

w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 15}))
_acct = Account.from_key(os.environ["WALLET_PRIVATE_KEY"]) if os.getenv("WALLET_PRIVATE_KEY") else None

# GuardVault: the on-chain policy contract every transfer goes through (see contracts/GuardVault.sol)
_DEPLOY = os.path.join(BASE_DIR, "contracts", "deployment.json")
vault = None
VAULT_ADDRESS = None
if os.path.exists(_DEPLOY):
    _d = json.load(open(_DEPLOY))
    VAULT_ADDRESS = Web3.to_checksum_address(_d["address"])
    vault = w3.eth.contract(address=VAULT_ADDRESS, abi=_d["abi"])

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
    key = re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()
    c = load_contacts()
    c[key] = Web3.to_checksum_address(address)
    save_contacts(c)
    if vault is not None:
        _vault_tx(vault.functions.setContact(key, Web3.to_checksum_address(address)))
        return f"Saved {name} to your on-chain contacts."
    return f"Saved contact {name}."


def resolve_recipient(who: str) -> tuple[str, str]:
    """Return (label, checksum address) for a contact name or 0x address."""
    who = who.strip()
    if Web3.is_address(who):
        addr = Web3.to_checksum_address(who)
        return addr[:6] + "…" + addr[-4:], addr
    key = re.sub(r"[^a-z0-9 ]", "", who.lower()).strip()
    if vault is not None and _acct is not None and key:
        try:
            onchain = vault.functions.contactOf(_acct.address, key).call()
            if int(onchain, 16) != 0:
                return key.title(), Web3.to_checksum_address(onchain)
        except Exception:
            pass  # fall back to the local mirror below
    c = load_contacts()
    if key in c:
        return key.title(), Web3.to_checksum_address(c[key])
    raise WalletError(f"I don't have a contact named '{who}'.")


# ── reads ───────────────────────────────────────────────────────────────────
def address() -> str:
    if not _acct:
        raise WalletError("No wallet configured.")
    return _acct.address


def balance(addr: str | None = None) -> Decimal:
    """Plain wallet balance in MON."""
    a = Web3.to_checksum_address(addr or address())
    return Decimal(w3.from_wei(w3.eth.get_balance(a), "ether"))


def vault_balance() -> Decimal:
    """MON the user has deposited in their GuardVault (what the agent is allowed to spend)."""
    if vault is None:
        return balance()
    return Decimal(w3.from_wei(vault.functions.balanceOf(address()).call(), "ether"))


def policy() -> dict:
    """The spending policy enforced on-chain by GuardVault."""
    if vault is None:
        return {"configured": False, "max_per_tx": MAX_SEND, "daily_limit": MAX_SEND, "trusted_only": False}
    p = vault.functions.policyOf(address()).call()  # (configured, trustedOnly, maxPerTx, dailyLimit, agent)
    return {"configured": p[0], "trusted_only": p[1],
            "max_per_tx": Decimal(w3.from_wei(p[2], "ether")), "daily_limit": Decimal(w3.from_wei(p[3], "ether"))}


def tx_status(tx_hash: str) -> str:
    try:
        r = w3.eth.get_transaction_receipt(tx_hash)
        return "confirmed" if r.status == 1 else "failed"
    except Exception:
        return "pending"


def explorer_url(tx_hash: str) -> str:
    return f"{EXPLORER}/tx/{tx_hash}"


# ── writes ──────────────────────────────────────────────────────────────────
def _vault_tx(fn, value: int = 0, wait: bool = True) -> str:
    """Sign and broadcast a GuardVault call from the app wallet."""
    if not _acct:
        raise WalletError("No wallet configured.")
    tx = fn.build_transaction({
        "from": _acct.address, "nonce": w3.eth.get_transaction_count(_acct.address),
        "chainId": CHAIN_ID, "gasPrice": w3.eth.gas_price, "value": value,
    })
    try:
        tx["gas"] = int(w3.eth.estimate_gas(tx) * 1.3)
    except Exception as e:  # a revert here means a GuardVault rule blocked it
        raise WalletError(_revert_reason(e))
    h = w3.eth.send_raw_transaction(_acct.sign_transaction(tx).raw_transaction).hex()
    h = h if h.startswith("0x") else "0x" + h
    if wait:
        r = w3.eth.wait_for_transaction_receipt(h, timeout=60)
        if r.status != 1:
            raise WalletError("The transaction failed on-chain.")
    return h


def _revert_reason(e: Exception) -> str:
    m = re.search(r"execution reverted: ([^'\")]+)", str(e))
    return ("Blocked by GuardVault: " + m.group(1).strip()) if m else f"Transaction rejected: {str(e)[:120]}"


def parse_amount(amount) -> Decimal:
    try:
        d = Decimal(str(amount))
    except InvalidOperation:
        raise WalletError(f"'{amount}' is not a valid amount.")
    if d <= 0:
        raise WalletError("Amount must be positive.")
    return d


def prepare_transfer(to: str, amount) -> dict:
    """Validate everything client-side and return a summary. Does NOT send. The contract re-checks on-chain."""
    label, addr = resolve_recipient(to)
    amt = parse_amount(amount)
    pol = policy()
    if amt > pol["max_per_tx"]:
        raise WalletError(f"That is above your safety limit of {pol['max_per_tx'].normalize():f} MON per transfer.")
    bal = vault_balance()
    if bal < amt:
        raise WalletError(f"Your vault only has {bal:.4f} MON.")
    named = not Web3.is_address(to.strip())
    return {"label": label, "to": addr, "amount": amt, "contact": re.sub(r"[^a-z0-9 ]", "", to.lower()).strip() if named else ""}


def send_mon(prep: dict, approved_by: str = "voice") -> str:
    """Send through GuardVault.guardedSend. Callers MUST have obtained confirmation first.
    `approved_by` ("voice", "double-blink", "button", ...) is recorded permanently on-chain."""
    if vault is None:
        raise WalletError("GuardVault is not deployed.")
    fn = vault.functions.guardedSend(
        _acct.address, prep.get("contact", ""),
        prep["to"] if not prep.get("contact") else "0x0000000000000000000000000000000000000000",
        w3.to_wei(prep["amount"], "ether"), approved_by,
    )
    return _vault_tx(fn)
