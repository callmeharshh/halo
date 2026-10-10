"""Capture real Halo UI frames for the video (no money moves: the refusal is blocked and the confirm card is cancelled)."""
import os, subprocess, sys, time, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
from dotenv import load_dotenv; load_dotenv(os.path.join(ROOT, ".env"))
import cdp
PORT = 8772; OUT = os.path.join(ROOT, "video", "assets")
env = dict(os.environ, VAULT_OWNER=os.getenv("HALO_TEST_OWNER", "0xb5848eF465b06Ade36461e0f49aE2809Bae08b98"))
srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "halo.py"), "--no-browser", "--port", str(PORT)], cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
b = None
try:
    for _ in range(60):
        try: urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/status", timeout=3); break
        except Exception: time.sleep(1)
    b = cdp.Chrome(1280, 720)
    b.send("Emulation.setDeviceMetricsOverride", width=1280, height=720, deviceScaleFactor=1, mobile=False)
    b.open(f"http://127.0.0.1:{PORT}/", settle=2)
    b.eval("sessionStorage.setItem('haloSplash','1')")
    b.wait("/\\d+\\.\\d+/.test(document.querySelector('#vaultVal').innerText)", 25)
    time.sleep(2.5); b.screenshot(os.path.join(OUT, "ui_idle.png"), full=False); print("idle ok")
    say = lambda t: b.eval("(()=>{const i=document.querySelector('#typeIn'); i.value=%r; document.querySelector('#typeForm').requestSubmit();})()" % t)
    say("send 5 MON to Alice")
    b.wait("/limit|above|can.?t|cannot/i.test(document.querySelector('#haloText').innerText)", 60); time.sleep(1.8)
    b.screenshot(os.path.join(OUT, "ui_refused.png"), full=False); print("refused ok:", b.eval("document.querySelector('#haloText').innerText")[:90])
    time.sleep(8)
    say("send 0.05 MON to Alice")
    b.wait("!document.querySelector('#confirmOv').hidden", 60); time.sleep(1.5)
    b.screenshot(os.path.join(OUT, "ui_confirm.png"), full=False); print("confirm ok")
    time.sleep(6); b.eval("document.querySelector('#cfNo').click()"); time.sleep(2)
finally:
    if b: b.close()
    srv.terminate()
