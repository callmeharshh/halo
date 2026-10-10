"""Voice accuracy lab: YOU read each line aloud, we show what the speech model heard and score it.
   python tests/voice_lab.py            (about 3 minutes; results saved to tests/voice_lab_results.json)
Tip: speak naturally at your normal distance from the mic, in the room where you will demo."""
import json, os, sys, threading, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv; load_dotenv(os.path.join(ROOT, ".env"))
from rapidfuzz import fuzz
import safety
from voice import Voice

LINES = [
    ("Open Safari.", "command"),
    ("Send zero point zero five MON to Alice.", "payment"),
    ("Confirm.", "confirm"),
    ("Cancel.", "cancel"),
    ("Haan.", "confirm"),
    ("Nahi, ruko.", "cancel"),
    ("Is this message safe?", "command"),
    ("Mera balance kitna hai?", "hinglish"),
    ("Alice ko do MON bhej do.", "hinglish payment"),
    ("Dear team, the meeting is moved to three PM tomorrow.", "dictation"),
    ("The integral of x squared from zero to three equals nine.", "dictation"),
    ("Send point five MON to Alice.", "payment"),
]
got, ev = [], threading.Event()
v = Voice(lambda t: (got.append(t), ev.set()))
v.start()
results = []
print("\nHALO VOICE LAB. Read each line when prompted. Ctrl+C to stop.\n")
time.sleep(1)
for text, kind in LINES:
    got.clear(); ev.clear()
    print(f"  SAY  ▶ {text}   [{kind}]")
    if not ev.wait(25):
        print("       (nothing heard within 25 s)\n"); results.append({"said": text, "heard": "", "score": 0, "kind": kind}); continue
    heard = " ".join(got)
    score = round(fuzz.ratio(safety_norm := "".join(c for c in text.lower() if c.isalnum() or c == " "), "".join(c for c in heard.lower() if c.isalnum() or c == " ")))
    extra = ""
    if kind == "payment":
        nums = safety.numbers_in(heard); extra = f"  amounts heard: {[str(n) for n in nums]}"
    if kind in ("confirm", "cancel"):
        extra = f"  classified as: {safety.classify_reply(heard)}"
    print(f"       HEARD: {heard}   → {score}% similar{extra}\n")
    results.append({"said": text, "heard": heard, "score": score, "kind": kind, "extra": extra.strip()})
    time.sleep(1.2)
v.stop()
avg = sum(r["score"] for r in results) / len(results)
json.dump({"avg_similarity": avg, "results": results}, open(os.path.join(ROOT, "tests", "voice_lab_results.json"), "w"), indent=1, ensure_ascii=False)
print(f"AVERAGE SIMILARITY {avg:.0f}%  (saved to tests/voice_lab_results.json)")
bad = [r for r in results if r["score"] < 80]
print("Lines below 80%:", [r["said"] for r in bad] or "none")
