"""On-chain + repo consistency checks (read-only, no money moves)."""
import json, os, sys, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv; load_dotenv(os.path.join(ROOT, ".env"))
import wallet as wl
fails = []
def check(name, ok, extra=""):
    print(("  PASS " if ok else "  FAIL ") + name + (f"  [{extra}]" if extra and not ok else ""))
    if not ok: fails.append(name)
def warn(name, ok, extra=""):
    print(("  PASS " if ok else "  WARN ") + name + (f"  [{extra}]" if extra and not ok else ""))

d = json.load(open(os.path.join(ROOT, "contracts/deployment.json"))); addr = d["address"]
check("chain id is Monad testnet (10143)", wl.with_retry(lambda: wl.w3.eth.chain_id) == 10143)
check("GuardVault has bytecode at the deployed address", len(wl.with_retry(lambda: wl.w3.eth.get_code(addr))) > 1000)
for f in ("docs/contract.js", "ui/contract.js", "README.md"):
    check(f"{f} references the deployed address", addr in open(os.path.join(ROOT, f)).read())
try:
    import requests
    j = requests.get(f"https://sourcify-api-monad.blockvision.org/v2/contract/10143/{addr}", timeout=20).json()
    check("source is verified on Sourcify (runtime match)", j.get("runtimeMatch") == "match" or j.get("match") == "match", str(j)[:100])
except Exception as e:
    check("source is verified on Sourcify (runtime match)", False, str(e)[:80])
check("contract has recorded real transfers", wl.with_retry(lambda: wl.vault.functions.totalTransfers().call()) > 0)

owner = os.getenv("HALO_TEST_OWNER") or wl.OWNER
pol = wl.with_retry(lambda: wl.vault.functions.policyOf(owner).call())
check("demo family vault has rules configured", pol[0])
check("demo family vault approves THIS device as agent", pol[5].lower() == wl.address().lower(), f"agent={pol[5]}")
warn("demo family vault is not paused", not pol[2], "it is PAUSED: resume it in the Family Console")
bal = wl.with_retry(lambda: wl.vault.functions.balanceOf(owner).call()) / 1e18
warn(f"demo family vault funded for the demo (>= 0.3 MON, has {bal:.3f})", bal >= 0.3, "top it up in the Family Console")
gas = float(wl.balance())
warn(f"device wallet has gas (>= 0.02 MON, has {gas:.3f})", gas >= 0.02, "fund it from the faucet")
print("\nCONTRACT CHECK:", "ALL PASSED" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
