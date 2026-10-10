"""Dev mock of the Halo Journeys backend: serves docs/ and /api/{config,plan,tts} on :8798.
Run: .venv/bin/python travel/dev_mock.py   (MOCK_FAIL=1 makes /api/plan emit an error; MOCK_TTS=0 makes /api/tts fail)"""
import asyncio, json, os
from pathlib import Path
from aiohttp import web

DOCS = Path(__file__).resolve().parent.parent / "docs"
STAGES = ["Understanding your request…", "Researching Pune airport accessibility…", "Researching Goa airport accessibility…",
          "Checking hotels with accessible rooms…", "Reading traveller attestations on Monad…", "Drafting messages to venues…"]


async def config(_): return web.json_response({"live": True, "tts": True})


async def plan(req):
    body = await req.json()
    resp = web.StreamResponse(headers={"Content-Type": "application/x-ndjson", "Cache-Control": "no-cache"})
    await resp.prepare(req)
    send = lambda o: resp.write((json.dumps(o, ensure_ascii=False) + "\n").encode())
    for s in STAGES:
        await send({"event": "stage", "text": s}); await asyncio.sleep(0.5)
    if os.getenv("MOCK_FAIL") or "FAIL" in body.get("request", ""):
        await send({"event": "error", "text": "The research service is busy. Please try again."})
    else:
        data = json.loads((DOCS / "dev-fixture.json").read_text())
        data["traveler"]["needs"] = body.get("needs") or data["traveler"]["needs"]
        await send({"event": "result", "data": data})
    await resp.write_eof(); return resp


async def tts(req):
    if os.getenv("MOCK_TTS") == "0": return web.Response(status=503, text="tts off")
    return web.Response(body=b"\xff\xfb\x90\x00" + b"\x00" * 400, content_type="audio/mpeg")


async def index(_): raise web.HTTPFound("/journeys.html")


app = web.Application()
app.add_routes([web.get("/api/config", config), web.post("/api/plan", plan), web.post("/api/tts", tts), web.get("/", index),
                web.static("/", DOCS, show_index=False)])
if __name__ == "__main__":
    web.run_app(app, host="127.0.0.1", port=8798)
