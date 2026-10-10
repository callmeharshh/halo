"""Headless-Chrome checks for docs/journeys.html against travel/dev_mock.py (:8798). Usage: python travel/devtools/check_journeys.py [--send]"""
import os, sys, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tests"))
import cdp
from dotenv import dotenv_values
SEND = "--send" in sys.argv
URL = "http://127.0.0.1:8798/journeys.html"
SH = os.path.join(os.path.dirname(__file__), "..", "..", "tests", "shots")
key = dotenv_values(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))["HALO_TEST_FAMILY_KEY"]
fails = []
def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)
    if not ok: fails.append(name)

def run(w, h, tag):
    b = cdp.Chrome(w, h)
    try:
        b.send("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=(w < 500))
        b.open(URL, preload=cdp.mock_wallet(key), settle=3)
        check(f"{tag} live mode", b.eval("document.body.dataset.mode") == "live")
        b.eval("document.getElementById('req').value=''")
        b.eval("document.querySelector('#examples button').click()")
        check(f"{tag} example fills", "Pune to Goa" in b.eval("document.getElementById('req').value"))
        b.eval("document.querySelector('input[name=need][value=wheelchair]').click()")
        b.screenshot(f"{SH}/j_{tag}_form.png", full=False)
        b.eval("document.getElementById('go').click()")
        time.sleep(1.5)
        check(f"{tag} progress shown", b.eval("document.querySelectorAll('#stages li').length") >= 2, str(b.eval("document.querySelectorAll('#stages li').length")))
        b.screenshot(f"{SH}/j_{tag}_progress.png", full=False)
        check(f"{tag} result", b.wait("!document.getElementById('result').hidden && document.querySelectorAll('.j-place').length>5", 20))
        check(f"{tag} chain read", b.wait("document.querySelectorAll('.j-badge.b-load').length==0", 60), str(b.eval("[...document.querySelectorAll('.j-badge')].map(x=>x.textContent).join('|')")))
        check(f"{tag} no chain errors", b.eval("document.querySelectorAll('[data-role=retry]:not([hidden])').length")==0)
        b.screenshot(f"{SH}/j_{tag}_result.png", full=True)
        # no horizontal overflow
        check(f"{tag} no h-scroll", b.eval("document.documentElement.scrollWidth<=window.innerWidth+1"), str(b.eval("document.documentElement.scrollWidth")))
        # small targets
        small = b.eval("[...document.querySelectorAll('button,a[href],input:not([type=hidden]),summary')].filter(e=>e.offsetParent&&!e.closest('.j-chip')&&(()=>{const r=e.getBoundingClientRect();return r.height<47.5||r.width<47.5})()).map(e=>(e.textContent||e.name).trim().slice(0,30)).slice(0,10)")
        check(f"{tag} targets>=48px", not small, str(small))
        # draft
        b.eval("document.querySelector('[data-role=draftbtn]').click()")
        check(f"{tag} draft reveals", b.eval("!document.querySelector('.j-draft').hidden && !!document.querySelector('.j-draft a[href^=\"https://wa.me/\"]')"))
        # TTS fallback / mp3
        b.eval("document.getElementById('read').click()")
        time.sleep(1.5); print("  read status:", b.eval("document.getElementById('read-status').textContent"))
        # dialog + keyboard
        b.eval("document.querySelectorAll('.j-place')[0].querySelectorAll('.j-acts .j-btn')[1].click()")
        check(f"{tag} dialog opens+focus", b.eval("document.activeElement.id")=="dlg")
        for _ in range(40): b.send("Input.dispatchKeyEvent", type="keyDown", key="Tab", code="Tab", windowsVirtualKeyCode=9); b.send("Input.dispatchKeyEvent", type="keyUp", key="Tab", code="Tab", windowsVirtualKeyCode=9)
        check(f"{tag} focus trapped", b.eval("!!document.activeElement.closest('#dlg')"))
        b.screenshot(f"{SH}/j_{tag}_dialog.png", full=False)
        b.send("Input.dispatchKeyEvent", type="keyDown", key="Escape", code="Escape", windowsVirtualKeyCode=27)
        check(f"{tag} Esc closes + focus returns", b.eval("document.getElementById('dlg-back').hidden") and b.eval("!!document.activeElement.closest('.j-acts')"))
        # prefs
        b.eval("document.querySelector('[data-size=\"2\"]').click();document.getElementById('contrast').click()")
        b.screenshot(f"{SH}/j_{tag}_bigcontrast.png", full=False)
        check(f"{tag} prefs persisted", b.eval("localStorage.getItem('halo.j.size')=='2'&&localStorage.getItem('halo.j.contrast')=='1'"))
        b.eval("document.querySelector('[data-size=\"0\"]').click();document.getElementById('contrast').click()")
        if SEND and tag == "d":
            fix = json.load(open(os.path.join(os.path.dirname(__file__), "..", "..", "docs", "dev-fixture.json")))
            b.eval("""window.__t=null;(()=>{const p=document.querySelectorAll('.j-place')[0];})()""")
            # swap place identity to the test place via re-render of a fake plan
            fake = {"title":"Test","summary":"t","traveler":{"needs":[],"notes":""},"days":[],"tips":[],"generated_at":"",
              "places":[{"name":"Halo Journeys Test Place","city":"Pune","kind":"attraction","access":{"features":{},"summary":"test","confidence":"low","sources":[]}}]}
            # expose renderPlan via sample path: intercept fetch for sample-plan.json
            b.eval("window.__fake=%s" % json.dumps(fake))
            b.eval("(()=>{const of=window.fetch;window.fetch=(u,o)=>String(u).includes('sample-plan.json')?Promise.resolve(new Response(JSON.stringify(window.__fake))):of(u,o)})();document.getElementById('sample-btn').click()")
            check("fake plan", b.wait("document.querySelectorAll('.j-place').length==1 && document.querySelector('.j-badge.b-load')==null", 40))
            if b.eval("document.querySelector('.j-place h3').textContent")!="Halo Journeys Test Place": print("ABORT wrong place"); return
            before = b.eval("document.querySelector('[data-role=chain-line]').textContent"); print("  before:", before)
            b.eval("[...document.querySelectorAll('.j-acts .j-btn')].find(x=>x.textContent.includes('I have been')).click()")
            b.eval("document.querySelector('#att-feats input').click();document.querySelectorAll('#att-feats input')[1].click();document.getElementById('att-note').value='Automated test of Halo Journeys'")
            if "--fake-hash" in sys.argv:
                b.eval("(()=>{const r=window.ethereum.request.bind(window.ethereum);window.ethereum.request=(a)=>a.method=='eth_sendTransaction'?Promise.resolve('0x6d5df3f327aa5f142425e3743d3b3468fdaf13c0df9d3920c39898cfeedd7e5b'):r(a)})()")
            b.eval("document.getElementById('att-go').click()")
            seen=set()
            for _ in range(80):
                t=b.eval("document.getElementById('att-status').textContent") or ""
                if t not in seen: seen.add(t); print("  status:", t[:110])
                if t.startswith("Done") or "Could not" in t: break
                time.sleep(1.5)
            print("  mockErrors:", b.eval("JSON.stringify(window.__mockErrors||[])"))
            check("attest done", b.eval("document.getElementById('att-status').textContent").startswith("Done"))
            check("tx link", b.eval("!!document.querySelector('#att-status a[href*=\"testnet.monadscan.com/tx/0x\"]')"))
            b.send("Input.dispatchKeyEvent", type="keyDown", key="Escape", code="Escape", windowsVirtualKeyCode=27)
            check("badge refreshed", b.wait("document.querySelector('.j-badge').textContent.includes('1 traveller')", 40), str(b.eval("document.querySelector('.j-badge').textContent")))
            b.screenshot(f"{SH}/j_{tag}_attested.png", full=False)
        check(f"{tag} zero console errors", not b.errors, str(b.errors[:5]))
    finally:
        b.close()

def sample():
    b = cdp.Chrome(390, 900)
    try:
        b.open("http://127.0.0.1:8801/journeys.html", settle=3)
        check("sample mode", b.eval("document.body.dataset.mode")=="sample")
        check("sample banner", "Sample plan generated by the agent" in (b.eval("document.getElementById('banner').textContent") or ""))
        b.wait("document.querySelectorAll('.j-badge.b-load').length==0",60)
        b.screenshot(f"{SH}/j_sample.png", full=True)
        check("sample zero console errors", not b.errors, str(b.errors[:5]))
    finally: b.close()

if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv)>1 and not sys.argv[1].startswith("--") else "all"
    if which in ("all","m"): run(390, 844, "m")
    if which in ("all","d"): run(1280, 900, "d")
    if which in ("all","s"): sample()
    print("FAILS:", fails)
