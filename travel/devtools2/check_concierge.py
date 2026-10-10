"""Headless-Chrome checks for docs/concierge.html. Needs travel/dev_mock2.py on :8797 (live) and `python -m http.server 8796` in docs/ (sample).
Usage: python travel/devtools2/check_concierge.py   (never submits a transaction)"""
import os, sys, json, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "tests"))
import cdp
from dotenv import dotenv_values
LIVE, SAMPLE = "http://127.0.0.1:8797/concierge.html", "http://127.0.0.1:8796/concierge.html"
SH = os.path.join(os.path.dirname(__file__), "..", "..", "tests", "shots")
key = dotenv_values(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))["HALO_TEST_FAMILY_KEY"]
fails = []
def check(name, ok, extra=""):
    print(("PASS " if ok else "FAIL ") + name, extra)
    if not ok: fails.append(name)
def mk(w, h, scheme="light"):
    b = cdp.Chrome(w, h)
    b.send("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=(w < 500))
    b.send("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme}])
    return b
def key_press(b, k, code=None):
    for t in ("keyDown", "keyUp"):
        b.send("Input.dispatchKeyEvent", type=t, key=k, code=code or k, windowsVirtualKeyCode={"Enter": 13, "Tab": 9, "Escape": 27}.get(k, 0))
def type_text(b, text):
    b.send("Input.insertText", text=text)

def live(w, h, tag, scheme="light"):
    b = mk(w, h, scheme)
    try:
        b.open(LIVE, preload=cdp.mock_wallet(key), settle=2.5)
        check(f"{tag} live mode", b.eval("document.body.dataset.mode") == "live")
        check(f"{tag} 6 prompt chips", b.eval("document.querySelectorAll('.prompt').length") == 6)
        check(f"{tag} 15 agent rows", b.eval("document.querySelectorAll('#agents li').length") == 15)
        b.screenshot(f"{SH}/c_{tag}_empty.png", full=False)
        # keyboard: focus composer, type, Enter
        b.eval("document.getElementById('composer-input').focus()")
        type_text(b, "Plan 3 days Pune to Goa, I use a wheelchair, budget 30000 rupees")
        key_press(b, "Enter")
        check(f"{tag} user bubble", b.wait("document.querySelectorAll('.msg.user').length==1", 5))
        check(f"{tag} chip appears", b.wait("document.querySelectorAll('.hand').length>=1", 8))
        check(f"{tag} working dot while streaming", b.wait("document.querySelectorAll('.hand.working').length>=1", 8))
        b.screenshot(f"{SH}/c_{tag}_working.png", full=False)
        check(f"{tag} plan card in trip", b.wait("document.querySelectorAll('#arts .place').length==6", 30))
        check(f"{tag} done (no working chips)", b.wait("document.querySelectorAll('.hand.working').length==0 && !document.getElementById('send').getAttribute('aria-label').startsWith('Stop')", 40))
        check(f"{tag} agent msg + word-split ok", b.eval("[...document.querySelectorAll('.msg.agent .bubble')].some(x=>x.textContent.includes('3 days from Pune'))"))
        check(f"{tag} bold rendered", b.eval("!!document.querySelector('.msg.agent .bubble strong')"))
        check(f"{tag} agents counts", b.eval("[...document.querySelectorAll('#agents .cnt')].some(x=>x.textContent==='1')"))
        check(f"{tag} badges resolved", b.wait("document.querySelectorAll('.place .badge.b-load').length==0", 60), str(b.eval("[...document.querySelectorAll('.place .badge')].map(x=>x.textContent).join('|')")))
        check(f"{tag} no retry shown", b.eval("document.querySelectorAll('[data-role=retry]:not([hidden])').length")==0)
        time.sleep(1)
        b.screenshot(f"{SH}/c_{tag}_plan.png", full=False)
        # turn 2 & 3 via chips
        for q in ("What should I pack and prepare?", "Review my plan for risks"):
            b.eval(f"document.getElementById('composer-input').focus()")
            type_text(b, q); key_press(b, "Enter")
            time.sleep(1)
            b.wait("document.querySelectorAll('.hand.working').length==0 && document.getElementById('send').getAttribute('aria-label')=='Send message'", 40)
        kinds = b.eval("[...document.querySelectorAll('#arts .art')].map(a=>a.dataset.kind).join(',')")
        check(f"{tag} artifact kinds", all(k in kinds for k in ("plan", "budget", "checklist", "guardrails", "drafts", "schedule")), kinds)
        check(f"{tag} simulated tag on schedule", b.eval("!!document.querySelector('.art[data-kind=schedule] .sim')"))
        check(f"{tag} no horizontal overflow", b.eval("document.documentElement.scrollWidth<=window.innerWidth+1"))
        # extras
        for q in ("Suggest accessible destinations in India for a blind traveller", "The lift at my hotel is broken, what now?"):
            b.eval("document.getElementById('composer-input').focus()"); type_text(b, q); key_press(b, "Enter"); time.sleep(1)
            b.wait("document.querySelectorAll('.hand.working').length==0 && document.getElementById('send').getAttribute('aria-label')=='Send message'", 40)
        check(f"{tag} inspiration + barrier", b.eval("!!document.querySelector('.art[data-kind=inspiration] .dcard') && !!document.querySelector('.art[data-kind=barrier] .opt')"))
        b.eval("document.querySelector('.art[data-kind=inspiration] .dcard').click()")
        check(f"{tag} destination fills composer", "Plan 3 days in Jaipur" in (b.eval("document.getElementById('composer-input').value") or ""))
        b.eval("document.getElementById('composer-input').value=''")
        # error
        b.eval("document.getElementById('composer-input').focus()"); type_text(b, "FAIL please"); key_press(b, "Enter")
        check(f"{tag} error row", b.wait("!!document.querySelector('.bubble.err')", 10))
        b.eval("document.querySelector('#agents') && document.getElementById('ptab-agents').click()")
        b.screenshot(f"{SH}/c_{tag}_agents.png", full=False)
        b.eval("document.getElementById('ptab-trip').click()")
        # all artifact kinds via debug hook (render defensively incl. empty data)
        kinds = {"transit": {"legs": [{"from": "Goa Airport", "to": "Hotel", "mode": "Accessible taxi", "assistance": "Driver helps with ramp", "tip": "Pre-book"}]},
                 "checkin": {"flight": "6E123", "opens": "24h before", "seat": "12C", "note": "x", "simulated": True},
                 "booking": {"items": [{"label": "Flight", "detail": "d", "price": "INR 5500"}, {"label": "Taxi", "price": 1200}], "simulated": True},
                 "feedback": {"questions": ["How was the ramp?"], "attest_suggestion": {"place": "Miramar Beach", "city": "Goa", "features": [0, 1]}},
                 "weird": {"a": 1}, "budget2": None}
        for k, d in kinds.items():
            b.eval("window.haloConcierge.emit(%s)" % json.dumps({"event": "artifact", "kind": k.replace("2", ""), "title": "T " + k, "data": d}))
        b.eval("window.haloConcierge.emit({event:'artifact',kind:'plan',title:'empty',data:{}})")
        check(f"{tag} defensive kinds", b.eval("document.querySelectorAll('#arts .art').length")>=12, str(b.eval("document.querySelectorAll('#arts .art').length")))
        b.eval("document.querySelector('.art[data-kind=feedback] .btn-primary').click()")
        check(f"{tag} attest from feedback prefilled", b.eval("!document.getElementById('dlg-back').hidden && document.querySelectorAll('#att-feats input:checked').length")==2)
        b.eval("document.getElementById('att-close').click()")
        check(f"{tag} no console errors", not b.errors, str(b.errors))
    finally:
        b.close()

def attest(w, h):
    b = mk(w, h)
    try:
        b.open(LIVE, preload=cdp.mock_wallet(key), settle=2.5)
        b.eval("document.getElementById('composer-input').focus()"); type_text(b, "Plan 3 days Pune to Goa, I use a wheelchair, budget 30000 rupees"); key_press(b, "Enter")
        b.wait("document.querySelectorAll('#arts .place').length==6", 30)
        b.wait("document.getElementById('send').getAttribute('aria-label')=='Send message' && document.querySelectorAll('.hand.working').length==0", 30); time.sleep(1)
        b.eval("document.querySelector('#arts .place [data-role=retry]').previousElementSibling.click()")
        check("attest dialog opens from place card", b.wait("!document.getElementById('dlg-back').hidden", 5))
        check("dialog focus inside", b.eval("document.getElementById('dlg').contains(document.activeElement)"))
        time.sleep(.8); b.screenshot(f"{SH}/c_attest_{w}.png", full=False)
        key_press(b, "Escape")
        check("Escape closes dialog", b.wait("document.getElementById('dlg-back').hidden", 3))
        # draft toggle
        b.eval("document.querySelector('#arts .place [aria-controls]').click()")
        check("draft opens", b.eval("!document.querySelector('#arts .draft').hidden"))
        # reload: log restored
        b.open(LIVE, preload=cdp.mock_wallet(key), settle=3)
        check("transcript restored after reload", b.eval("document.querySelectorAll('.msg.user').length")==1 and b.eval("document.querySelectorAll('#arts .place').length")==6)
        check("no console errors (attest)", not b.errors, str(b.errors))
    finally:
        b.close()

def profile(w, h):
    b = mk(w, h)
    try:
        b.open(LIVE, settle=2)
        b.eval("document.getElementById('profile-btn').click()")
        check("drawer opens", b.wait("!document.getElementById('drawer-back').hidden", 3))
        b.eval("""(()=>{const f=document.getElementById('profile-form');f.name.value='Priya';f.aids.value='Manual wheelchair';f.home_city.value='Pune';f.budget.value='30000';f.ecn.value='Asha';f.ecp.value='9999999999';f.email.value='p@example.com';
          f.querySelector('input[name=need][value=wheelchair]').click();f.querySelector('input[name=language][value=hi]').click();})()""")
        time.sleep(.8); b.screenshot(f"{SH}/c_profile_{w}.png", full=False)
        b.eval("document.getElementById('pf-save').click()")
        check("chip text", b.eval("document.getElementById('profile-chip-text').textContent") == "Priya · wheelchair", str(b.eval("document.getElementById('profile-chip-text').textContent")))
        b.open(LIVE, settle=2)
        check("persists after reload", b.eval("document.getElementById('profile-chip-text').textContent") == "Priya · wheelchair")
        b.eval("document.getElementById('composer-input').focus()"); type_text(b, "hello there"); key_press(b, "Enter"); time.sleep(2)
        log = open("/tmp/m2.log").read()
        check("profile sent with chat", '"home_city": "Pune"' in log and '"budget_inr": 30000' in log and '"lang": "hi"' in log, log[-300:])
        b.eval("document.querySelector('.seg-b[data-size=\"2\"]').click(); document.getElementById('contrast').click()")
        b.open(LIVE, settle=1.5)
        check("size+contrast persist", b.eval("document.documentElement.dataset.size==='2' && document.documentElement.dataset.contrast==='high'"))
    finally:
        b.close()

def sample(w, h, tag, scheme="light"):
    b = mk(w, h, scheme)
    try:
        b.open(SAMPLE, preload=cdp.mock_wallet(key), settle=2)
        check(f"{tag} sample mode", b.eval("document.body.dataset.mode") == "sample" and not b.eval("document.getElementById('banner').hidden"))
        check(f"{tag} typing user msg", b.wait("document.querySelectorAll('.msg.user').length>=1", 8))
        check(f"{tag} replay finishes", b.wait("document.querySelectorAll('.msg.user').length==4 && !document.getElementById('send').getAttribute('aria-label').startsWith('Stop') && document.querySelectorAll('.hand.working').length==0 && document.querySelectorAll('#arts .art').length>=9", 240), str(b.eval("document.querySelectorAll('#arts .art').length")))
        time.sleep(4)
        check(f"{tag} simulated tags", b.eval("document.querySelectorAll('.sim').length")>=2, str(b.eval("document.querySelectorAll('.sim').length")))
        check(f"{tag} badges via chain in sample mode", b.wait("document.querySelectorAll('.place .badge.b-load').length==0", 60))
        b.screenshot(f"{SH}/c_{tag}_end.png", full=False)
        b.eval("document.getElementById('composer-input').focus()"); type_text(b, "Tell me a joke"); key_press(b, "Enter")
        check(f"{tag} polite local-only reply", b.wait("[...document.querySelectorAll('.msg.agent .bubble')].some(x=>x.textContent.includes('Run the concierge locally'))", 10))
        check(f"{tag} no console errors", not b.errors, str(b.errors))
        n = b.eval("document.getElementById('replay-btn').click(); 1")
        time.sleep(3); check(f"{tag} replay restarts", b.eval("document.querySelectorAll('.msg.user').length")<=2)
    finally:
        b.close()

if __name__ == "__main__":
    what = sys.argv[1:] or ["live", "attest", "profile", "sample"]
    if "live" in what: live(1280, 860, "L1280"); live(390, 844, "L390", "dark")
    if "attest" in what: attest(1280, 860); attest(390, 844)
    if "profile" in what: profile(1280, 860); profile(390, 844)
    if "sample" in what: sample(1280, 860, "S1280")
    print("FAILS:", fails); sys.exit(1 if fails else 0)
