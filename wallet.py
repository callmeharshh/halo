"""Monad testnet wallet layer. Pure functions, no LLM, no UI."""
import json
import os
import re
import time
from decimal import Decimal, InvalidOperation

from dotenv import load_dotenv
from web3 import Web3
from eth_account import Account

from safety import match_contact

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.getenv("HALO_ENV_PATH") or os.path.join(BASE_DIR, ".env"))

# Public RPCs sometimes return empty/failed results under load. Measured: Ankr was the most reliable from browsers.
# We keep several endpoints and rotate on transient failures (never on a contract revert, which is a real answer).
_DEFAULT_RPCS = ["https://rpc.ankr.com/monad_testnet", "https://testnet-rpc.monad.xyz", "https://rpc-testnet.monadinfra.com"]
RPCS = list(dict.fromkeys(([os.environ["MONAD_RPC"]] if os.getenv("MONAD_RPC") else []) + _DEFAULT_RPCS))
RPC = RPCS[0]
CHAIN_ID = int(os.getenv("MONAD_CHAIN_ID", "10143"))
EXPLORER = "https://testnet.monadscan.com"
CONTACTS_PATH = os.path.join(BASE_DIR, "contacts.json")
MAX_SEND = Decimal(os.getenv("MAX_SEND_MON", "1"))  # hard safety cap per transfer

_rpc_i = 0
w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 15}))


def _rotate_rpc():
    global _rpc_i
    _rpc_i = (_rpc_i + 1) % len(RPCS)
    w3.provider = Web3.HTTPProvider(RPCS[_rpc_i], request_kwargs={"timeout": 15})


def _is_revert(e: Exception) -> bool:
    return "execution reverted" in str(e).lower() or type(e).__name__ == "ContractLogicError"


def with_retry(fn, tries: int = 5):
    """Run an RPC call, rotating endpoints on transient failures. Reverts are answers, so they are re-raised."""
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            if _is_revert(e):
                raise
            last = e
            _rotate_rpc()
            time.sleep(0.25 * (i + 1))
    raise last
_acct = Account.from_key(os.environ["WALLET_PRIVATE_KEY"]) if os.getenv("WALLET_PRIVATE_KEY") else None

# GuardVault: the on-chain policy contract every transfer goes through (see contracts/GuardVault.sol)
_DEPLOY = os.path.join(BASE_DIR, "contracts", "deployment.json")
vault = None
VAULT_ADDRESS = None
if os.path.exists(_DEPLOY):
    _d = json.load(open(_DEPLOY))
    VAULT_ADDRESS = Web3.to_checksum_address(_d["address"])
    vault = w3.eth.contract(address=VAULT_ADDRESS, abi=_d["abi"])

# OWNER = whose vault/policy/contacts we spend from. Solo mode: this wallet. Family mode (VAULT_OWNER set): a family
# member's wallet owns the vault and sets the rules; this device only holds the agent key and cannot change them.
OWNER = (Web3.to_checksum_address(os.environ["VAULT_OWNER"]) if os.getenv("VAULT_OWNER")
         else (_acct.address if _acct else None))
FAMILY_MODE = bool(_acct and OWNER and OWNER != _acct.address)

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
    if FAMILY_MODE:
        raise WalletError("Only your family can add contacts. Ask them to add this person in the Family Console.")
    key = re.sub(r"[^a-z0-9 ]", "", name.lower()).strip()
    c = load_contacts()
    c[key] = Web3.to_checksum_address(address)
    save_contacts(c)
    if vault is not None:
        _vault_tx(vault.functions.setContact(key, Web3.to_checksum_address(address)))
        return f"Saved {name} to your on-chain contacts."
    return f"Saved contact {name}."


def contact_book() -> dict:
    """name -> address from the owner's ON-CHAIN contact book (falls back to the local mirror if offline)."""
    if vault is not None and OWNER:
        try:
            names, addrs = with_retry(lambda: vault.functions.contactsOf(OWNER).call())
            return {n: Web3.to_checksum_address(a) for n, a in zip(names, addrs)}
        except Exception:
            pass
    return {k: Web3.to_checksum_address(v) for k, v in load_contacts().items()}


def resolve_recipient(who: str) -> tuple[str, str]:
    """Return (label, checksum address) for a contact name or 0x address."""
    who = who.strip()
    if Web3.is_address(who):
        addr = Web3.to_checksum_address(who)
        return addr[:6] + "…" + addr[-4:], addr
    key = re.sub(r"[^a-z0-9 ]", "", who.lower()).strip()
    book = contact_book()
    matched, why = match_contact(key, list(book.keys()))  # tolerate mishearing, refuse ambiguity
    if matched is None:
        raise WalletError(f"I couldn't be sure who you meant: {why}. Please say the name again.")
    return matched.title(), book[matched]


# ── reads ───────────────────────────────────────────────────────────────────
def address() -> str:
    if not _acct:
        raise WalletError("No wallet configured.")
    return _acct.address


def balance(addr: str | None = None) -> Decimal:
    """Plain wallet balance in MON."""
    a = Web3.to_checksum_address(addr or address())
    return Decimal(w3.from_wei(with_retry(lambda: w3.eth.get_balance(a)), "ether"))


def vault_balance() -> Decimal:
    """MON in the OWNER's GuardVault (what this agent is allowed to spend)."""
    if vault is None:
        return balance()
    return Decimal(w3.from_wei(with_retry(lambda: vault.functions.balanceOf(OWNER).call()), "ether"))


def policy() -> dict:
    """The spending policy enforced on-chain by GuardVault (set by the owner, not by this device)."""
    if vault is None:
        return {"configured": False, "max_per_tx": MAX_SEND, "daily_limit": MAX_SEND, "trusted_only": False,
                "paused": False, "agent_ok": True}
    p = with_retry(lambda: vault.functions.policyOf(OWNER).call())  # (configured, trustedOnly, paused, maxPerTx, dailyLimit, agent)
    return {"configured": p[0], "trusted_only": p[1], "paused": p[2],
            "max_per_tx": Decimal(w3.from_wei(p[3], "ether")), "daily_limit": Decimal(w3.from_wei(p[4], "ether")),
            "agent_ok": (p[5].lower() == address().lower()) or not FAMILY_MODE}


def tx_status(tx_hash: str) -> str:
    try:
        r = with_retry(lambda: w3.eth.get_transaction_receipt(tx_hash))
        return "confirmed" if r.status == 1 else "failed"
    except Exception:
        return "pending"


def explorer_url(tx_hash: str) -> str:
    return f"{EXPLORER}/tx/{tx_hash}"


# ── writes ──────────────────────────────────────────────────────────────────
def _vault_tx(fn, value: int = 0, wait: bool = True) -> str:
    """Sign and broadcast a GuardVault call from the app wallet, surviving flaky RPCs without double-sending."""
    if not _acct:
        raise WalletError("No wallet configured.")

    def build():
        return fn.build_transaction({
            "from": _acct.address, "nonce": w3.eth.get_transaction_count(_acct.address, "pending"),
            "chainId": CHAIN_ID, "gasPrice": w3.eth.gas_price, "value": value,
        })
    try:
        tx = with_retry(build)
        tx["gas"] = int(with_retry(lambda: w3.eth.estimate_gas(tx)) * 1.3)
    except Exception as e:  # a revert here means a GuardVault rule blocked it
        raise WalletError(_revert_reason(e))
    signed = _acct.sign_transaction(tx)
    h = signed.hash.hex()
    h = h if h.startswith("0x") else "0x" + h
    try:
        with_retry(lambda: w3.eth.send_raw_transaction(signed.raw_transaction))
    except Exception as e:
        if not re.search(r"already known|known transaction|nonce too low|already imported", str(e), re.I):
            raise WalletError(f"Could not send the transaction: {str(e)[:100]}")
        # a previous attempt reached the network: the same signed tx is already in flight, so just wait for it
    if wait:
        r = with_retry(lambda: w3.eth.wait_for_transaction_receipt(h, timeout=60))
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
    if pol["paused"]:
        raise WalletError("Payments are paused by your family.")
    if not pol["agent_ok"]:
        raise WalletError("This device is not approved to spend. Ask your family to approve it in the Family Console.")
    if amt > pol["max_per_tx"]:
        raise WalletError(f"That is above your safety limit of {pol['max_per_tx'].normalize():f} MON per transfer.")
    bal = vault_balance()
    if bal < amt:
        raise WalletError(f"Your vault only has {bal:.4f} MON.")
    named = not Web3.is_address(to.strip())
    return {"label": label, "to": addr, "amount": amt, "contact": label.lower() if named else ""}


def send_mon(prep: dict, approved_by: str = "voice") -> str:
    """Send through GuardVault.guardedSend. Callers MUST have obtained confirmation first.
    `approved_by` ("voice", "double-blink", "button", ...) is recorded permanently on-chain."""
    if vault is None:
        raise WalletError("GuardVault is not deployed.")
    fn = vault.functions.guardedSend(
        OWNER, prep.get("contact", ""),
        prep["to"] if not prep.get("contact") else "0x0000000000000000000000000000000000000000",
        w3.to_wei(prep["amount"], "ether"), approved_by,
    )
    return _vault_tx(fn)
