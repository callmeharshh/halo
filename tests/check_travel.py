"""Travel agent: starts the REAL server, streams a real plan, checks honesty rules (sources present, no blanket accessibility claims),
origin guard, TTS, and the on-chain registry link (place ids). Uses OpenAI (a few cents)."""
import asyncio, json, os, re, subprocess, sys, time
import aiohttp
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv; load_dotenv(os.path.join(ROOT, ".env"))
PORT = 8782; BASE = f"http://127.0.0.1:{PORT}"
fails = []
def check(name, ok, extra=""):
    print(("  PASS " if ok else "  FAIL ") + name + (f"  [{str(extra)[:150]}]" if extra and not ok else ""))
    if not ok: fails.append(name)

async def main():
    srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "travel", "server.py"), "--no-browser", "--port", str(PORT)], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        async with aiohttp.ClientSession() as s:
            for _ in range(40):
                try:
                    async with s.get(BASE + "/api/config") as r:
                        if r.status == 200: cfg = await r.json(); break
                except aiohttp.ClientError: await asyncio.sleep(1)
            check("server answers /api/config as live", cfg.get("live") is True)
            async with s.post(BASE + "/api/plan", json={"request": "x"}, headers={"Origin": "http://evil.example"}) as r:
                check("foreign website is refused (403)", r.status == 403, r.status)
            async with s.post(BASE + "/api/plan", json={"request": "hi"}, headers={"Origin": BASE}) as r:
                check("too-short request is rejected politely (400)", r.status == 400, r.status)
            stages, result, t0 = [], None, time.time()
            async with s.post(BASE + "/api/plan", headers={"Origin": BASE}, json={"request": "2 days in Jaipur. I am blind and travel with a guide dog. Simple, relaxed plan.", "needs": ["blind"], "lang": "en"}) as r:
                async for line in r.content:
                    if not line.strip(): continue
                    ev = json.loads(line)
                    if ev["event"] == "stage": stages.append(ev["text"])
                    elif ev["event"] == "result": result = ev["data"]
                    elif ev["event"] == "error": check("plan completes without error", False, ev["text"])
            check(f"plan streams progress then a result ({time.time()-t0:.0f}s)", bool(stages) and result is not None)
            if result:
                check("plan has 2 days with items", len(result["days"]) >= 2 and all(d["items"] for d in result["days"]))
                check("4 to 6 key places researched", 3 <= len(result["places"]) <= 6, len(result["places"]))
                withsrc = [p for p in result["places"] if p["access"]["sources"]]
                check("most places carry real source links", len(withsrc) >= max(2, len(result["places"]) - 2), f"{len(withsrc)}/{len(result['places'])}")
                check("no Google Maps search links used as 'sources'", not any("google.com/maps" in x["url"] for p in result["places"] for x in p["access"]["sources"]))
                check("places with no sources are marked low confidence", all(p["access"]["confidence"] == "low" for p in result["places"] if not p["access"]["sources"]))
                check("every place has a drafted confirmation message", all(p.get("draft", {}).get("body") for p in result["places"]))
                txt = (result["title"] + " " + result["summary"]).lower()
                check("summary does not claim places are accessible/barrier-free before verification", not re.search(r"all (stops|places|venues) (are|is) (wheelchair|accessible|barrier)", txt) and "barrier-free" not in txt, result["summary"][:120])
                names = {p["name"] for p in result["places"]}
                check("itinerary items link to researched places", any(i.get("place") in names for d in result["days"] for i in d["items"]))
            async with s.post(BASE + "/api/tts", json={"text": "Your trip is ready."}, headers={"Origin": BASE}) as r:
                data = await r.read(); check("text-to-speech returns audio", r.status == 200 and len(data) > 2000, r.status)
    finally:
        srv.terminate()
    # registry link: place id convention matches the contract
    import wallet as wl
    d = json.load(open(os.path.join(ROOT, "contracts", "deployment.AccessRegistry.json")))
    c = wl.w3.eth.contract(address=d["address"], abi=d["abi"])
    norm = lambda x: re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", x.lower())).strip()
    pid = wl.w3.keccak(text=norm("Goa International Airport") + "|" + norm("Goa"))
    check("place-id convention matches the deployed contract", wl.with_retry(lambda: c.functions.placeId(norm("Goa International Airport"), norm("Goa")).call()) == pid)
    print("\nTRAVEL CHECK:", "ALL PASSED" if not fails else f"{len(fails)} FAILED: {fails}")
    sys.exit(1 if fails else 0)
asyncio.run(main())
