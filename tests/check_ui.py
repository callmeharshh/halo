"""End-to-end UI check: real halo.py server + real ui/ in headless Chrome.

  python tests/check_ui.py            # cancels the payment (no money moves)
  python tests/check_ui.py --live-tx  # approves one 0.05 MON payment through the on-screen Confirm button
Env: HALO_TEST_OWNER (family vault owner address) is used as VAULT_OWNER. Screenshots go to tests/shots/.
"""
import os, subprocess, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = "--live-tx" in sys.argv
PORT = 8767
URL = f"http://127.0.0.1:{PORT}/"
OWNER = os.getenv("HALO_TEST_OWNER", "0xb5848eF465b06Ade36461e0f49aE2809Bae08b98")
SHOTS = os.path.join(ROOT, "tests", "shots"); os.makedirs(SHOTS, exist_ok=True)
fails = []
def check(name, ok, extra=""):
    print(("  PASS " if ok else "  FAIL ") + name + (f"  [{extra}]" if extra and not ok else ""))
    if not ok: fails.append(name)

if not cdp.available():
    print("  SKIP (Chrome not found)"); sys.exit(0)
env = dict(os.environ, VAULT_OWNER=OWNER)
srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "halo.py"), "--no-browser", "--port", str(PORT)], cwd=ROOT, env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
b = None
try:
    for _ in range(60):
        try: urllib.request.urlopen(URL + "api/status", timeout=2); break
        except Exception: time.sleep(1)
    b = cdp.Chrome(1280, 800)
    b.open(URL, settle=2)
    q = lambda sel, prop="innerText": b.eval(f"(document.querySelector('{sel}')||{{}}).{prop}")
    check("UI connects to the server (no 'reconnecting')", bool(b.wait("document.querySelector('#conn') && !/reconnect|offline/i.test(document.querySelector('#conn').innerText)", 20)))
    check("vault chip shows the real balance", bool(b.wait("/\\d+\\.\\d+/.test(document.querySelector('#vaultVal').innerText)", 25)), q("#vaultVal"))
    check("limits chip shows the on-chain rules", bool(b.wait("/per|\\/tx|0\\./.test(document.querySelector('#limitsVal').innerText)", 25)), q("#limitsVal"))
    check("guard chip links the contract", "Guard" in (q("#chipGuard") or "") or bool(q("#guardVal")))
    check("setup banner hidden when vault is configured", b.eval("document.querySelector('#setupBanner').hidden") in (True, None) or not b.eval("getComputedStyle(document.querySelector('#setupBanner')).display !== 'none'"))
    b.screenshot(os.path.join(SHOTS, "companion_idle.png"), full=False)

    b.eval("(()=>{const i=document.querySelector('#typeIn'); i.value='what time is it'; i.dispatchEvent(new Event('input',{bubbles:true})); document.querySelector('#typeForm').requestSubmit();})()")
    check("typed command: Halo's reply caption appears", bool(b.wait("document.querySelector('#haloText').innerText.length > 5 && /\\d/.test(document.querySelector('#haloText').innerText)", 40)), q("#haloText"))
    check("user caption shows what was said", "time" in (q("#userText") or "").lower())
    check("agent timeline shows routing + tool", bool(b.wait("document.querySelector('#timeline').innerText.includes('System')", 5)))

    b.eval("(()=>{const i=document.querySelector('#typeIn'); i.value='send 0.05 MON to Alice'; document.querySelector('#typeForm').requestSubmit();})()")
    check("payment: confirmation card appears", bool(b.wait("!document.querySelector('#confirmOv').hidden", 60)))
    check("card shows amount, recipient", "0.05" in (q("#cfAmt") or "") and "Alice" in (q("#cfTo") or ""), f"{q('#cfAmt')} / {q('#cfTo')}")
    b.screenshot(os.path.join(SHOTS, "confirm_card.png"), full=False)
    time.sleep(6)  # Guardian arms after the read-back; clicking a button works any time, voice only after arming
    b.eval("document.querySelector('#%s').click()" % ("cfYes" if LIVE else "cfNo"))
    check("card closes after the click", bool(b.wait("document.querySelector('#confirmOv').hidden", 20)))
    if LIVE:
        ok = b.wait("document.querySelector('#timeline').innerText.includes('monadscan.com/tx/0x') || document.querySelector('#toasts').innerText.includes('monadscan') || document.querySelector('#toasts').innerHTML.includes('monadscan.com/tx/0x')", 60)
        check("approved payment: tx link shown in the UI", bool(ok))
    else:
        check("cancelled payment: Halo says so", bool(b.wait("/cancel|not sent|nothing/i.test(document.querySelector('#haloText').innerText)", 40)), q("#haloText"))
    b.screenshot(os.path.join(SHOTS, "after_payment.png"), full=False)

    b.eval("document.querySelector('#tab-family').click()"); time.sleep(1)
    check("Family tab shows the device address", bool(b.wait("/0x[0-9a-fA-F]{40}/.test(document.querySelector('#devAddr').innerText)", 10)))
    check("pairing link carries ?device=", "console.html?device=0x" in (q("#pairLink", "value") or q("#pairLink") or ""), q("#pairLink"))
    b.screenshot(os.path.join(SHOTS, "family.png"), full=False)
    check("no JavaScript errors during the whole session", not b.errors, str(b.errors[:2]))
finally:
    if b: b.close()
    srv.terminate()
print("\nUI CHECK:", "ALL PASSED" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
