"""Concierge chat UI against the REAL server (live mode): send a message, watch agent hand-offs and artifacts render.
Uses the pre-cached demo request (instant). Also checks sample replay on a static server."""
import functools, http.server, os, subprocess, sys, threading, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdp
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
fails = []
def check(name, ok, extra=""):
    print(("  PASS " if ok else "  FAIL ") + name + (f"  [{str(extra)[:140]}]" if extra and not ok else ""))
    if not ok: fails.append(name)
if not cdp.available():
    print("  SKIP (Chrome not found)"); sys.exit(0)
MSG = "3 days from Pune to Goa. I use a wheelchair. Budget about 30000 rupees. Beaches and good food, no stairs."
# ---- sample replay (static server, no backend)
class Q(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
st = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Q, directory=os.path.join(ROOT, "docs")))
threading.Thread(target=st.serve_forever, daemon=True).start()
b = cdp.Chrome(1280, 800)
try:
    b.send("Emulation.setDeviceMetricsOverride", width=1280, height=800, deviceScaleFactor=1, mobile=False)
    b.open(f"http://127.0.0.1:{st.server_port}/concierge.html", settle=2)
    check("sample mode: replay banner is shown", bool(b.wait("/Replaying a real session/i.test(document.querySelector('#banner').innerText)", 15)))
    check("sample mode: agent hand-offs appear in the transcript", bool(b.wait("/planning agent/i.test(document.querySelector('#transcript').innerText)", 60)))
    check("sample mode: artifacts reach the Trip panel", bool(b.wait("document.querySelector('#trip-count').innerText.trim()>='3'", 90)))
    check("sample mode: simulated steps are labelled", bool(b.wait("/Simulated in this demo/i.test(document.body.innerText)", 90)))
    check("sample mode: no JavaScript errors", not b.errors, str(b.errors[:2]))
finally:
    b.close(); st.shutdown()
# ---- live mode (real server)
PORT = 8784
srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "travel", "server.py"), "--no-browser", "--port", str(PORT)], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
b = None
try:
    for _ in range(40):
        try: urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/config", timeout=3); break
        except Exception: time.sleep(1)
    b = cdp.Chrome(1280, 800)
    b.send("Emulation.setDeviceMetricsOverride", width=1280, height=800, deviceScaleFactor=1, mobile=False)
    b.open(f"http://127.0.0.1:{PORT}/concierge.html", settle=2.5)
    check("live mode: no replay banner (talks to the real agent)", bool(b.wait("document.querySelector('#banner').hidden===true", 15)))
    b.eval("(()=>{const i=document.querySelector('#composer-input');i.value=%r;i.dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('#send').click()})()" % MSG)
    check("live: planning agent hand-off appears", bool(b.wait("/planning agent/i.test(document.querySelector('#transcript').innerText)", 90)))
    check("live: the plan artifact reaches the Trip panel", bool(b.wait("/Itinerary|Day 1/i.test(document.querySelector('#arts').innerText)", 120)))
    check("live: the concierge's final message arrives (with Read aloud)", bool(b.wait("/Read aloud/.test(document.querySelector('#transcript').innerText)", 60)))
    check("live: no JavaScript errors", not b.errors, str(b.errors[:2]))
    b.screenshot(os.path.join(ROOT, "tests", "shots", "concierge_live.png"), full=False)
finally:
    if b: b.close()
    srv.terminate()
print("\nCONCIERGE CHECK:", "ALL PASSED" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
