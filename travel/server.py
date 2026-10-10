"""Halo Journeys local server.   python travel/server.py   -> http://127.0.0.1:8780
Serves the web page (docs/journeys.html) and the live API: /api/config, /api/plan (streaming), /api/tts."""
import argparse
import asyncio
import json
import os
import re
import sys
import webbrowser

from aiohttp import web

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "travel"))
from dotenv import load_dotenv
load_dotenv(os.getenv("HALO_ENV_PATH") or os.path.join(ROOT, ".env"))
import agent  # noqa: E402
import concierge  # noqa: E402

DOCS = os.path.join(ROOT, "docs")
allowed_origins: set[str] = set()


@web.middleware
async def guard(request, handler):
    if request.method == "POST":  # block other websites from using your OpenAI key through this local server
        origin = request.headers.get("Origin")
        if origin and origin not in allowed_origins:
            return web.Response(status=403, text="forbidden origin")
    resp = await handler(request)
    resp.headers["Cache-Control"] = "no-store"
    return resp


async def config(request):
    return web.json_response({"live": True, "tts": bool(os.getenv("OPENAI_API_KEY"))})


async def plan(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"event": "error", "text": "bad request"}, status=400)
    text = str(body.get("request", "")).strip()[:1200]
    needs = [str(n) for n in body.get("needs", []) if isinstance(n, str)][:5]
    lang = "hi" if body.get("lang") == "hi" else "en"
    if len(text) < 8:
        return web.json_response({"event": "error", "text": "Please describe your trip a little more (where, how long, what you need)."}, status=400)
    resp = web.StreamResponse(headers={"Content-Type": "application/x-ndjson", "X-Accel-Buffering": "no"})
    await resp.prepare(request)
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    emit = lambda ev: loop.call_soon_threadsafe(q.put_nowait, ev)

    def run():
        try:
            emit({"event": "result", "data": agent.plan(text, needs, lang, emit)})
        except Exception as e:
            emit({"event": "error", "text": "Sorry, planning failed: " + str(e)[:120]})
        finally:
            emit(None)

    loop.run_in_executor(None, run)
    while True:
        ev = await q.get()
        if ev is None:
            break
        await resp.write((json.dumps(ev, ensure_ascii=False) + "\n").encode())
    await resp.write_eof()
    return resp


async def chat(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"event": "error", "text": "bad request"}, status=400)
    msg = str(body.get("message", "")).strip()[:1500]
    if not msg:
        return web.json_response({"event": "error", "text": "empty message"}, status=400)
    sid = re.sub(r"[^a-zA-Z0-9_-]", "", str(body.get("session", "default")))[:60] or "default"
    profile = body.get("profile") if isinstance(body.get("profile"), dict) else {}
    lang = "hi" if body.get("lang") == "hi" else "en"
    resp = web.StreamResponse(headers={"Content-Type": "application/x-ndjson", "X-Accel-Buffering": "no"})
    await resp.prepare(request)
    loop = asyncio.get_running_loop()
    q: asyncio.Queue = asyncio.Queue()
    emit = lambda ev: loop.call_soon_threadsafe(q.put_nowait, ev)

    def run():
        try:
            concierge.chat(sid, msg, profile, lang, emit)
        except Exception as e:
            emit({"event": "error", "text": "Sorry, something went wrong: " + str(e)[:120]})
            emit({"event": "done"})
        finally:
            emit(None)
    loop.run_in_executor(None, run)
    while True:
        ev = await q.get()
        if ev is None:
            break
        await resp.write((json.dumps(ev, ensure_ascii=False) + "\n").encode())
    await resp.write_eof()
    return resp


async def tts(request):
    try:
        body = await request.json()
        text = str(body.get("text", "")).strip()[:3500]
    except Exception:
        return web.Response(status=400)
    if not text:
        return web.Response(status=400)

    def synth():
        r = agent.client.audio.speech.create(model=os.getenv("OPENAI_TTS_MODEL", "tts-1"), voice=os.getenv("OPENAI_TTS_VOICE", "nova"),
                                             input=text, response_format="mp3", speed=1.0)
        return r.read()
    try:
        audio = await asyncio.get_running_loop().run_in_executor(None, synth)
    except Exception as e:
        return web.Response(status=502, text=str(e)[:100])
    return web.Response(body=audio, content_type="audio/mpeg")


async def index(request):
    return web.FileResponse(os.path.join(DOCS, "journeys.html"))


def make_app(port):
    allowed_origins.update({f"http://127.0.0.1:{port}", f"http://localhost:{port}"})
    app = web.Application(middlewares=[guard])
    app.router.add_get("/", index)
    app.router.add_get("/api/config", config)
    app.router.add_post("/api/plan", plan)
    app.router.add_post("/api/chat", chat)
    app.router.add_post("/api/tts", tts)
    app.router.add_static("/", DOCS, show_index=False)
    return app


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8780)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    url = f"http://127.0.0.1:{a.port}"
    if not a.no_browser:
        import threading
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    print(f"Halo Journeys running at {url}  (Ctrl+C to stop)")
    web.run_app(make_app(a.port), host="127.0.0.1", port=a.port, print=None)
