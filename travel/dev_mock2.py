"""Dev mock of the Halo Journeys Concierge backend: serves docs/ and /api/{config,chat,tts} on :8797.
Run: .venv/bin/python travel/dev_mock2.py   Streams scripted events built from docs/dev-session.json."""
import asyncio, json, re
from pathlib import Path
from aiohttp import web

DOCS = Path(__file__).resolve().parent.parent / "docs"
norm = lambda s: re.sub(r"[^a-z0-9 ]", " ", (s or "").lower()).split()


def session():
    return json.loads((DOCS / "dev-session.json").read_text())


EXTRAS = {
    "inspiration": [
        {"event": "agent", "name": "concierge", "status": "start"},
        {"event": "agent", "name": "inspiration_agent", "status": "start", "note": "Looking for step-free and tactile-friendly places"},
        {"event": "message", "agent": "inspiration_agent", "text": "Here are **three destinations** that suit a blind traveller well."},
        {"event": "artifact", "kind": "inspiration", "title": "Accessible destinations", "agent": "inspiration_agent", "data": {"places": [
            {"name": "Jaipur", "country": "India", "why": "Compact heritage core, guided touch tours at several museums.", "access_note": "Tactile models at Albert Hall; verify audio guides."},
            {"name": "Mysuru", "country": "India", "why": "Calm, walkable palace district and fragrant markets.", "access_note": "Palace has audio guide; uneven paving near the market."},
            {"name": "Pondicherry", "country": "India", "why": "Flat promenade, quiet French Quarter streets.", "access_note": "Few kerbs; confirm hotel Braille menus."}]}},
        {"event": "agent", "name": "inspiration_agent", "status": "done"},
        {"event": "agent", "name": "concierge", "status": "done"}, {"event": "done"}],
    "barrier": [
        {"event": "agent", "name": "concierge", "status": "start"},
        {"event": "agent", "name": "barrier_navigation_agent", "status": "start"},
        {"event": "message", "agent": "barrier_navigation_agent", "text": "I am sorry. A broken lift is a real barrier. Here are your **options**, quickest first."},
        {"event": "artifact", "kind": "barrier", "title": "Broken lift options", "agent": "barrier_navigation_agent", "data": {"issue": "The hotel lift is out of service and your room is on a higher floor.", "options": [
            {"title": "Ask for a ground-floor room", "detail": "Ask the front desk to move you now, in writing if possible.", "cost_hint": "Usually free"},
            {"title": "Move to a nearby accessible hotel", "detail": "I can shortlist step-free hotels within 2 km.", "cost_hint": "From 3,500 rupees a night"}]}},
        {"event": "agent", "name": "barrier_navigation_agent", "status": "done"},
        {"event": "agent", "name": "concierge", "status": "done"}, {"event": "done"}],
}
FALLBACK = [
    {"event": "agent", "name": "concierge", "status": "start"},
    {"event": "message", "agent": "concierge", "text": "I can plan a trip, suggest destinations, prepare a checklist, review risks or draft messages to venues. Tell me where you would like to go and what you need."},
    {"event": "agent", "name": "concierge", "status": "done"}, {"event": "done"}]


def pick(text):
    n = " ".join(norm(text)); t = set(n.split())
    for turn in session()["turns"]:
        if " ".join(norm(turn["user"])) == n:
            return turn["events"]
    if {"destinations", "inspire", "suggest"} & t: return EXTRAS["inspiration"]
    if {"lift", "broken", "elevator"} & t: return EXTRAS["barrier"]
    turns = session()["turns"]
    if {"pack", "prepare", "budget", "checklist"} & t: return turns[1]["events"]
    if {"risks", "review", "draft", "drafts", "messages"} & t: return turns[2]["events"]
    if {"plan", "goa", "days"} & t: return turns[0]["events"]
    return FALLBACK


async def config(_): return web.json_response({"live": True, "tts": True})


async def chat(req):
    body = await req.json()
    print("chat:", json.dumps({k: body.get(k) for k in ("session", "message", "lang")}), "profile:", json.dumps(body.get("profile")), flush=True)
    resp = web.StreamResponse(headers={"Content-Type": "application/x-ndjson", "Cache-Control": "no-cache"})
    await resp.prepare(req)
    if "FAIL" in (body.get("message") or ""):
        await resp.write(b'{"event":"error","text":"The research service is busy. Please try again."}\n'); await resp.write_eof(); return resp
    for ev in pick(body.get("message")):
        line = (json.dumps(ev, ensure_ascii=False) + "\n").encode()
        if ev["event"] == "message":  # split a line across two chunks to exercise buffering
            await resp.write(line[:20]); await asyncio.sleep(0.05); await resp.write(line[20:])
        else:
            await resp.write(line)
        await asyncio.sleep(0.45 if ev["event"] == "agent" else 0.2)
    await resp.write_eof(); return resp


async def tts(req): return web.Response(body=b"\xff\xfb\x90\x00" + b"\x00" * 400, content_type="audio/mpeg")


async def index(_): raise web.HTTPFound("/concierge.html")


app = web.Application()
app.add_routes([web.get("/api/config", config), web.post("/api/chat", chat), web.post("/api/tts", tts), web.get("/", index), web.static("/", DOCS, show_index=False)])
if __name__ == "__main__":
    web.run_app(app, host="127.0.0.1", port=8797)
