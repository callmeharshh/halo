"""The Family tab's one-click flow end to end: connect a wallet -> approve the device on-chain -> the device learns its owner.
Uses a mock wallet that signs REAL testnet txs (tiny gas) and a TEMP env file, so your real .env is never touched."""
import os, subprocess, sys, tempfile, time, json, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdp
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv; load_dotenv(os.path.join(ROOT, ".env"))
KEY = os.getenv("HALO_TEST_FAMILY_KEY"); PORT = 8769
fails = []
def check(name, ok, extra=""):
    print(("  PASS " if ok else "  FAIL ") + name + (f"  [{extra}]" if extra and not ok else ""))
    if not ok: fails.append(name)
if not KEY or not cdp.available():
    print("  SKIP (needs HALO_TEST_FAMILY_KEY and Chrome)"); sys.exit(0)
from eth_account import Account
fam = Account.from_key(KEY).address
tmp = tempfile.NamedTemporaryFile("w", suffix=".env", delete=False); tmp.write(open(os.path.join(ROOT, ".env")).read().replace("VAULT_OWNER=", "#VAULT_OWNER=")); tmp.close()
env = dict(os.environ, HALO_ENV_PATH=tmp.name); env.pop("VAULT_OWNER", None)
srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "halo.py"), "--no-browser", "--port", str(PORT)], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
b = None
try:
    st = None
    for _ in range(60):
        try: st = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/status", timeout=3)); break
        except Exception: time.sleep(1)
    check("server starts in SOLO mode (owner = device)", bool(st) and st["mode"] == "solo", str(st and st.get("mode")))
    b = cdp.Chrome(1280, 900)
    b.open(f"http://127.0.0.1:{PORT}/", preload=cdp.mock_wallet(KEY), settle=3)
    b.eval("document.querySelector('#tab-family').click()"); time.sleep(1)
    check("device address shown", bool(b.wait("/0x[0-9a-fA-F]{40}/.test(document.querySelector('#devAddr').innerText)", 15)))
    b.eval("document.querySelector('#connect').click()")
    check("MetaMask connects (mock) and the one-click button enables", bool(b.wait("!document.querySelector('#oneBtn').disabled", 40)))
    b.eval("document.querySelector('#oneBtn').click()")
    ok = b.wait("(()=>{const m=document.querySelector('#msg');return m&&m.dataset.kind==='ok'&&/All set|now owns/i.test(m.innerText)})()", 120)
    check("one-click finishes with a success message", bool(ok), b.eval("document.querySelector('#msg').dataset.kind+' | '+document.querySelector('#msg').innerText"))
    b.eval("window.HALO_QUICK_DEFAULTS={deposit:'0.001',max:'0.1',day:'0.3'}")
    b.eval("document.querySelector('#quickBtn').click()")
    done = b.wait("document.querySelectorAll('#quickSteps li.done').length===3", 150)
    check("Quick setup: all 3 checklist steps complete (fund, limits, Alice)", bool(done), b.eval("[...document.querySelectorAll('#quickSteps li')].map(l=>l.className).join(',')"))
    sys.path.insert(0, ROOT); import wallet as wl
    pol = wl.with_retry(lambda: wl.vault.functions.policyOf(fam).call())
    check("on-chain: limits are 0.1 / 0.3 and trusted-only", pol[1] and pol[3] == 10**17 and pol[4] == 3 * 10**17, str(pol))
    names, addrs = wl.with_retry(lambda: wl.vault.functions.contactsOf(fam).call())
    check("on-chain: 'alice' is a trusted contact", "alice" in names, str(names))
    time.sleep(2)
    st2 = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/status", timeout=10))
    check("the device now reports the connected wallet as its owner", st2["owner"].lower() == fam.lower() and st2["mode"] == "family", f"{st2['owner']} {st2['mode']}")
    check("owner was saved to the (temp) env file", f"VAULT_OWNER={fam}" in open(tmp.name).read())
    check("no JavaScript errors", not b.errors, str(b.errors[:2]))
finally:
    if b: b.close()
    srv.terminate(); os.unlink(tmp.name)
print("\nONE-CLICK CHECK:", "ALL PASSED" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
