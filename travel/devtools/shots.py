import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tests"))
import cdp
SH = os.path.join(os.path.dirname(__file__), "..", "..", "tests", "shots")
for w, h, tag in ((390, 844, "m"), (1280, 900, "d")):
    b = cdp.Chrome(w, h)
    b.send("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=(w < 500))
    b.open("http://127.0.0.1:8801/journeys.html", settle=3)
    b.wait("document.querySelectorAll('.j-badge.b-load').length==0", 60)
    for name, sel in (("banner", "#banner"), ("days", "#days"), ("place", ".j-place")):
        b.eval(f"document.querySelector('{sel}').scrollIntoView()"); time.sleep(.5)
        b.screenshot(f"{SH}/k_{tag}_{name}.png", full=False)
    print(tag, b.errors); b.close()
