"""Family Console end-to-end with a mock wallet that signs REAL Monad testnet transactions (spends tiny gas).
Needs HALO_TEST_FAMILY_KEY in .env (throwaway key of the demo family wallet). Run: python tests/check_console.py"""
import functools, http.server, os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdp
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from dotenv import load_dotenv; load_dotenv(os.path.join(ROOT, ".env"))
KEY = os.getenv("HALO_TEST_FAMILY_KEY")
fails = []
def check(name, ok, extra=""):
    print(("  PASS " if ok else "  FAIL ") + name + (f"  [{extra}]" if extra and not ok else ""))
    if not ok: fails.append(name)
if not KEY or not cdp.available():
    print("  SKIP (needs HALO_TEST_FAMILY_KEY and Chrome)"); sys.exit(0)

class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Q, directory=os.path.join(ROOT, "docs")))
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{srv.server_port}/console.html"
b = cdp.Chrome()
def status(): return b.eval("document.querySelector('#msg').dataset.kind + ' | ' + document.querySelector('#msg').innerText") or ""
def do(label, js, expect, timeout=75):
    b.eval(js)
    ok = b.wait(f"(()=>{{const m=document.querySelector('#msg');return m.dataset.kind==='ok'&&/{expect}/i.test(m.innerText)}})()", timeout)
    check(label, bool(ok), status())
def fill(i, v): return f"(()=>{{const e=document.getElementById('{i}');e.value='{v}';e.dispatchEvent(new Event('input',{{bubbles:true}}))}})()"
try:
    b.open(base + "?device=0xF54224dcD8eCD1D38c59a9e38Da333f3939402Ed", preload=cdp.mock_wallet(KEY), settle=3)
    check("pairing link prefills the device address", "0xF54224" in (b.eval("document.getElementById('agAddr').value") or ""))
    do("connect wallet (auto add/switch to Monad)", "document.getElementById('connect').click()", "Connected")
    check("dashboard loads the owner's vault", bool(b.wait("document.querySelector('#vBal').innerText.includes('MON')", 30)))
    do("pause payments (real tx)", "document.getElementById('pauseBtn').click()", "Paus")
    check("status shows Paused", bool(b.wait("document.querySelector('#vStatus').innerText.includes('Paused')", 30)))
    do("resume payments (real tx)", "document.getElementById('pauseBtn').click()", "Resum")
    check("status shows Active again", bool(b.wait("document.querySelector('#vStatus').innerText.includes('Active')", 30)))
    do("add contact (real tx)", fill("ctName", "checker") + ";" + fill("ctAddr", "0x000000000000000000000000000000000000dEaD") + ";document.getElementById('fContact').requestSubmit()", "checker")
    check("contact appears in the table", bool(b.wait("document.querySelector('#cBody').innerText.includes('checker')", 30)))
    do("remove contact (real tx)", "[...document.querySelectorAll('#cBody button')].find(x=>/checker/i.test(x.getAttribute('aria-label'))).click()", "Removing")
    check("contact removed", bool(b.wait("!document.querySelector('#cBody').innerText.includes('checker')", 30)))
    do("rejects a bad rule (per-payment > daily)", fill("polMax", "5") + ";" + fill("polDay", "1") + ";document.getElementById('fPolicy').requestSubmit()", "NEVER_MATCH", 1) if False else None
    b.eval(fill("polMax", "5") + ";" + fill("polDay", "1") + ";document.getElementById('fPolicy').requestSubmit()")
    check("client rejects per-payment limit above the daily limit", "cannot be higher" in (status()))
    check("no JavaScript errors", not b.errors, str(b.errors[:2]))
finally:
    b.close(); srv.shutdown()
print("\nCONSOLE CHECK:", "ALL PASSED" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
