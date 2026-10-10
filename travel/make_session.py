"""Record a REAL multi-turn concierge session into docs/sample-session.json (the public site replays it). Needs OPENAI_API_KEY.
   python travel/make_session.py"""
import json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "travel")); sys.path.insert(0, ROOT)
import concierge
PROFILE = {"name": "Priya", "needs": ["wheelchair"], "home": "Pune", "budget": 30000, "aids": "Manual wheelchair and a portable ramp",
           "assist": "Prefer an aisle seat near the front and early boarding", "emergency": "Aman (brother) +91 98xxxxxx01", "language": "English"}
TURNS = [
    "3 days from Pune to Goa. I use a wheelchair. Budget about 30000 rupees. Beaches and good food, no stairs.",
    "What should I prepare? Please set up the reminders and draft the messages to the hotel and the airline.",
    "The lift at my hotel is broken and my room is on the 4th floor. What now?",
    "Can you prepare the booking and plan my web check-in?",
]
out = {"profile": PROFILE, "recorded": time.strftime("%Y-%m-%d %H:%M"), "turns": []}
for i, msg in enumerate(TURNS, 1):
    ev, t = [], time.time()
    concierge.chat("sample", msg, PROFILE, "en", ev.append)
    ev = [e for e in ev if e.get("event") != "done"]
    out["turns"].append({"user": msg, "events": ev})
    print(f"turn {i}: {len(ev)} events in {time.time()-t:.0f}s | agents: {sorted({e['name'] for e in ev if e['event']=='agent' and e['status']=='start' and e['name']!='concierge'})}")
json.dump(out, open(os.path.join(ROOT, "docs", "sample-session.json"), "w"), indent=1, ensure_ascii=False)
print("wrote docs/sample-session.json")
