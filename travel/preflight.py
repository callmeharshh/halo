"""Live-demo preflight for Halo Journeys. Run right before presenting:   python travel/preflight.py"""
import json, os, socket, subprocess, sys, time, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "travel"))
from dotenv import load_dotenv; load_dotenv(os.path.join(ROOT, ".env"))
bad = warn = ok = 0
def row(level, text, hint=""):
    global bad, warn, ok
    icon = {"ok": "✅", "warn": "⚠️ ", "bad": "❌"}[level]
    if level == "ok": ok += 1
    elif level == "warn": warn += 1
    else: bad += 1
    print(f"{icon} {text}" + (f"\n     → {hint}" if hint and level != "ok" else ""))
DEMO = "3 days from Pune to Goa. I use a wheelchair. Budget about 30000 rupees. Beaches and good food, no stairs."
YOU = os.getenv("DEMO_WALLET", "0x7321B96eC8A116652C4d701371BEa23B6d199b39")

print("── Keys and network")
row("ok" if os.getenv("OPENAI_API_KEY", "").startswith("sk-") else "bad", "OPENAI_API_KEY set", "add it to .env")
try:
    from openai import OpenAI
    t = time.time(); OpenAI(timeout=20).chat.completions.create(model=os.getenv("OPENAI_MODEL", "gpt-4.1"), messages=[{"role": "user", "content": "ok"}], max_completion_tokens=3)
    dt = time.time() - t
    row("ok" if dt < 4 else "warn", f"OpenAI answers in {dt:.1f}s", "slow network: use the pre-cached request and the public replay as your fallback")
except Exception as e:
    row("bad", "OpenAI call failed", str(e)[:90])
try:
    import requests
    r = requests.post("https://places.googleapis.com/v1/places:searchText", timeout=15, headers={"X-Goog-Api-Key": os.getenv("GOOGLE_PLACES_API_KEY", ""), "Content-Type": "application/json", "X-Goog-FieldMask": "places.displayName"}, json={"textQuery": "Goa airport"})
    row("ok" if r.status_code == 200 else "warn", "Google Places API works (official accessibility data)", "check GOOGLE_PLACES_API_KEY; the agent still works with web sources only")
except Exception as e:
    row("warn", "Google Places unreachable", str(e)[:80])

print("\n── Monad and wallet")
try:
    import wallet as wl
    row("ok" if wl.with_retry(lambda: wl.w3.eth.chain_id) == 10143 else "bad", f"Monad testnet reachable via {wl.w3.provider.endpoint_uri}")
    reg = json.load(open(os.path.join(ROOT, "contracts", "deployment.AccessRegistry.json")))
    row("ok" if len(wl.with_retry(lambda: wl.w3.eth.get_code(reg["address"]))) > 500 else "bad", f"AccessRegistry live at {reg['address'][:10]}…")
    bal = float(wl.balance(YOU))
    row("ok" if bal >= 0.05 else "bad", f"your wallet {YOU[:8]}… holds {bal:.2f} MON (an attestation costs about 0.013)", "fund it at https://faucet.monad.xyz")
except Exception as e:
    row("bad", "Monad check failed", str(e)[:90])

print("\n── Concierge")
try:
    import concierge
    t = time.time(); evs = []
    concierge.chat("preflight", DEMO, {"needs": ["wheelchair"], "name": "Priya"}, "en", evs.append)
    dt = time.time() - t
    kinds = [e["kind"] for e in evs if e["event"] == "artifact"]
    row("ok" if "plan" in kinds else "bad", f"demo request returns a plan with {len(kinds)} artifacts in {dt:.1f}s")
    row("ok" if dt < 8 else "warn", "demo request is pre-cached (instant)" if dt < 8 else f"demo request took {dt:.0f}s (not cached): run it once now to warm the cache")
except Exception as e:
    row("bad", "concierge failed", str(e)[:90])
try:
    import agent
    r = agent.client.audio.speech.create(model="tts-1", voice="nova", input="Preflight.", response_format="mp3"); row("ok" if len(r.read()) > 2000 else "warn", "read-aloud (text to speech) works")
except Exception as e:
    row("warn", "text to speech failed", "the page falls back to the browser's voice")
for f in ("docs/sample-session.json", "docs/sample-plan.json", "docs/atts.json"):
    row("ok" if os.path.exists(os.path.join(ROOT, f)) else "bad", f"{f} present")
s = socket.socket(); busy = s.connect_ex(("127.0.0.1", 8780)) == 0; s.close()
row("warn" if busy else "ok", "port 8780 free" if not busy else "port 8780 in use (server already running?)", "that is fine if it is your Halo server")
print("\nBROWSER: use Chrome with MetaMask unlocked on Monad Testnet (chain 10143); keep a second tab on the public site as a fallback.")
print(f"{'='*50}\n✅ {ok}   ⚠️  {warn}   ❌ {bad}")
print("READY TO PRESENT" if bad == 0 else "FIX THE ❌ ITEMS")
sys.exit(1 if bad else 0)
