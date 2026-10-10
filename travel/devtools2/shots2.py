"""Screenshots of the concierge. Usage: python shots2.py <port> <w> <h> <tag> [wait_s] [light|dark] [js-to-run-after]"""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tests"))
import cdp
port, w, h, tag = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), sys.argv[4]
wait = float(sys.argv[5]) if len(sys.argv) > 5 else 4
scheme = sys.argv[6] if len(sys.argv) > 6 else "light"
js = sys.argv[7] if len(sys.argv) > 7 else None
SH = os.path.join(os.path.dirname(__file__), "..", "..", "tests", "shots")
b = cdp.Chrome(w, h)
try:
    b.send("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=(w < 500))
    b.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme}])
    b.open(f"http://127.0.0.1:{port}/concierge.html", settle=wait)
    if js:
        b.eval(js); time.sleep(1.5)
    b.screenshot(f"{SH}/c_{tag}.png", full=False)
    print("errors:", b.errors)
finally:
    b.close()
