"""Agent behaviour checks (uses OpenAI; NO money moves). Also measures Scam Shield accuracy on 8 samples."""
import base64, io, os, subprocess, sys, tempfile, threading, time, html
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv; load_dotenv(os.path.join(ROOT, ".env"))
os.environ["VAULT_OWNER"] = os.getenv("HALO_TEST_OWNER", "0xb5848eF465b06Ade36461e0f49aE2809Bae08b98")
import agents, cdp
fails = []
def check(name, ok, extra=""):
    print(("  PASS " if ok else "  FAIL ") + name + (f"  [{str(extra)[:140]}]" if extra and not ok else ""))
    if not ok: fails.append(name)

agents.bus.speak = lambda t: None
events = []
agents.bus.on_event = lambda a, k, t: events.append((a, k, t))
def ask(q): events.clear(); return agents.handle(q)

check("routes a system request to the System agent", "time" in ask("what time is it").lower() or any(a == "System" for a, k, t in events))
r = ask("send some money to Alice")
check("no amount said -> asks instead of sending", not any(k == "tx" for a, k, t in events) and len(r) > 3, r)
r = agents.t_send_mon("alice", 5)  # invented amount, user said none
agents.current_request = "send some money to Alice"
check("guard: amount not in the user's words is refused", "Not sent" in agents.t_send_mon("alice", 5))
agents.current_request = "send one MON to Alice"
r = agents.t_send_mon("alice", 1)
check("on-chain limit refuses an over-limit amount", "Rejected" in r and "limit" in r.lower(), r)
agents.current_request = "send 0.05 MON to Zoltan"
r = agents.t_send_mon("zoltan", 0.05)
check("unknown contact is refused", "Rejected" in r, r)

def feed(*utts):
    def run():
        t0 = time.time()
        while not agents.gate.armed and time.time() - t0 < 40: time.sleep(0.05)
        for u in utts:
            time.sleep(0.4); agents.gate.handle_utterance(u)
            if not agents.gate.active: break
    threading.Thread(target=run, daemon=True).start()
agents.gate.last_send = 0
agents.current_request = "send 0.05 MON to Alice"
feed("no cancel")
r = agents.t_send_mon("alice", 0.05)
check("voice 'cancel' stops a payment, nothing sent", "cancel" in r.lower() and not any(k == "tx" for a, k, t in events), r)
feed("the weather is lovely today", "nahi")
r = agents.t_send_mon("alice", 0.05)
check("stray chatter ignored, then 'nahi' cancels", "cancel" in r.lower(), r)

agents.current_request = "bhej do"
r = ask("mera balance kitna hai")
check("Hinglish request is understood and answered", len(r) > 5 and "MON" in r, r)

# ---- Scam Shield accuracy -------------------------------------------------------------------------------------------
SAMPLES = [
 ("scam", "Dear customer your Sunrise Bank KYC has expired, account will be BLOCKED today. Click http://sunrise-kyc.top/login and share OTP and PIN now."),
 ("scam", "CONGRATULATIONS! You won Rs 25,00,000 in the Lucky Draw. To claim, pay the Rs 2,500 processing fee to this UPI id: claim.prize@upi"),
 ("scam", "This is Cyber Police. A parcel in your name contains drugs. You are under DIGITAL ARREST. Stay on this video call and transfer Rs 50,000 to clear your name."),
 ("scam", "Hi Mom this is my NEW number, my phone broke. I am in an emergency and need Rs 20,000 right now. Send to this account and don't call, please. Don't tell Dad."),
 ("safe", "Beta, dinner on Sunday at 7. Mummy is making biryani. Bring your cousin too. See you soon!"),
 ("safe", "Your OTP for logging in to your bank app is 482913. It is valid for 10 minutes. Do not share this OTP with anyone. - Bank"),
 ("safe", "Reminder: your dentist appointment is tomorrow at 11:30 AM at Sai Dental Clinic, Baner. Reply YES to confirm or call us to reschedule."),
 ("safe", "Ramesh bhaiya, the society meeting is moved to Saturday 6 PM in the clubhouse. Please inform the watchmen. Thanks - Secretary"),
]
def shot(text):
    page = ("<!doctype html><meta charset=utf-8><body style='font:24px/1.5 system-ui;background:#eef;padding:50px'>"
            "<div style='max-width:640px;background:#fff;border-radius:18px;padding:26px;box-shadow:0 4px 20px #0003'>"
            "<div style='color:#666;font-size:15px;margin-bottom:10px'>New message</div>"
            f"<div style='background:#dcf8c6;border-radius:14px;padding:16px'>{html.escape(text)}</div></div>")
    b = cdp.Chrome(900, 560)
    try:
        b.open("data:text/html;base64," + base64.b64encode(page.encode()).decode(), settle=1.2)
        p = tempfile.mktemp(suffix=".png"); b.screenshot(p, full=False)
    finally:
        b.close()
    from PIL import Image
    buf = io.BytesIO(); Image.open(p).convert("RGB").save(buf, "JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode()

if cdp.available():
    right, rows = 0, []
    for label, text in SAMPLES:
        v = agents._vision(agents.SCAM_PROMPT, shot(text))
        said_scam = v.lower().startswith("this looks like a scam")
        ok = said_scam == (label == "scam")
        right += ok; rows.append((label, ok, v[:90]))
    for label, ok, v in rows: print(f"    [{label:4}] {'ok ' if ok else 'MISS'} {v}")
    check(f"Scam Shield accuracy on 8 samples: {right}/8 (need >= 7)", right >= 7, f"{right}/8")
    check("Scam Shield never calls a genuine OTP notice or family message a scam (no false alarms on 'safe')",
          all(ok for lab, ok, _ in rows if lab == "safe"))
else:
    print("  SKIP scam eval (Chrome not found)")
print("\nAGENT CHECK:", "ALL PASSED" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
