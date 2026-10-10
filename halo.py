"""Halo: local web UI server. Bridges the browser interface to voice, agents, Guardian, wallet and gaze.

    python halo.py            # starts on http://127.0.0.1:8765 and opens your browser
    python halo.py --no-browser --port 8765

The browser talks to us over a WebSocket at /ws (protocol documented in ui/). Everything is bound to
127.0.0.1 and the WebSocket rejects pages from other origins, so no website can drive your assistant.
"""
import argparse
import asyncio
import json
import os
import re
import subprocess
import sys
import threading
import time
import webbrowser

from aiohttp import WSMsgType, web
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(ROOT, ".env"))

import agents
import wallet as wl
from gaze import GazeController
from voice import Voice

UI_DIR = os.path.join(ROOT, "ui")
ENV_PATH = os.path.join(ROOT, ".env")

clients: set = set()
loop: asyncio.AbstractEventLoop | None = None
voice: Voice | None = None
gaze: GazeController | None = None
state = {"voice": "idle", "listening": False, "calibrating": False}
allowed_origins: set[str] = set()


# ── helpers: thread-safe push to every browser tab ───────────────────────────
def push(msg: dict):
    if loop is None or not clients:
        return
    data = json.dumps(msg)

    async def _send():
        for ws in list(clients):
            try:
                await ws.send_str(data)
            except Exception:
                clients.discard(ws)
    asyncio.run_coroutine_threadsafe(_send(), loop)


def fmt(d) -> str:
    return format(d.normalize(), "f") if d else "0"


def build_status() -> dict:
    s = {
        "mode": "family" if wl.FAMILY_MODE else "solo",
        "device": wl.address() if wl._acct else None,
        "owner": wl.OWNER,
        "contract": wl.VAULT_ADDRESS,
        "explorer": wl.EXPLORER,
        "llm": f"{agents.MODEL} ({'local' if agents.BACKEND == 'local' else 'cloud'})",
        "listening": state["listening"],
        "tts": {"engine": voice.tts_name() if voice else "system", "note": voice.tts_note() if voice else None},
        "assistant_mode": agents.mode,
        "gaze": {"calibrated": bool(gaze and gaze.calibrated), "on": bool(gaze and gaze.running.is_set()),
                 "calibrating": state["calibrating"]},
    }
    try:
        pol = wl.policy()
        s["vault"] = format(wl.vault_balance(), ".3f")
        s["wallet"] = format(wl.balance(), ".3f")
        s["policy"] = {"configured": pol["configured"], "max_per_tx": fmt(pol["max_per_tx"]),
                       "daily_limit": fmt(pol["daily_limit"]), "trusted_only": pol["trusted_only"],
                       "paused": pol["paused"], "agent_ok": pol["agent_ok"]}
        s["contacts"] = [{"name": n, "address": a} for n, a in wl.contact_book().items()]
    except Exception as e:  # RPC hiccup: UI keeps its last good numbers
        s["error"] = f"{type(e).__name__}: {str(e)[:80]}"
    return s


def push_status():
    def work():
        push({"type": "status", "data": build_status()})
    threading.Thread(target=work, daemon=True).start()


# ── wiring the pipeline to the UI ────────────────────────────────────────────
def on_event(agent, kind, text):
    push({"type": "event", "agent": agent, "kind": kind, "text": text})


def on_level(v: float):
    if clients and (state["voice"] in ("listening", "hearing", "speaking")):
        push({"type": "level", "value": round(float(v), 2)})


def on_voice_state(v):
    state["voice"] = v
    push({"type": "state", "value": v})


def speak(text):
    if voice:
        voice.speak(text)


_parts: list[str] = []
_parts_lock = threading.Lock()
_merge_timer: threading.Timer | None = None
_busy = threading.Event()
MERGE_SECONDS = 1.1  # a sentence split by a natural pause is merged into ONE request


def handle_utterance(text: str):
    """From the microphone. Confirmations go straight to the Guardian; everything else is merged and run one at a time."""
    global _merge_timer
    if agents.gate.handle_utterance(text):
        on_event("User", "say", text)
        return
    if agents.gate.active:
        return  # a payment is waiting: ignore unrelated speech
    with _parts_lock:
        _parts.append(text)
        if _merge_timer:
            _merge_timer.cancel()
        _merge_timer = threading.Timer(MERGE_SECONDS, _flush_parts)
        _merge_timer.daemon = True
        _merge_timer.start()


def _flush_parts():
    with _parts_lock:
        text = " ".join(_parts).strip()
        _parts.clear()
    if text:
        submit(text)


def submit(text: str):
    """Run ONE request at a time. A new request while Halo is still working is ignored (never two replies talking over each other)."""
    if _busy.is_set():
        push({"type": "toast", "level": "info", "text": "One moment, I am still working on your last request."})
        return
    _busy.set()
    threading.Thread(target=run_agents, args=(text,), daemon=True).start()


def run_agents(text):
    try:
        agents.handle(text)
    finally:
        _busy.clear()
        push_status()


def run_scam():
    try:
        push({"type": "state", "value": "thinking"})
        on_event("User", "say", "Check this message")
        reply = agents.t_scam_check()
        on_event("Vision", "reply", reply)
        on_event("Orchestrator", "reply", reply)
        speak(reply)
    except Exception as e:
        on_event("Vision", "error", str(e))
    finally:
        push({"type": "state", "value": "listening" if state["listening"] else "idle"})


def run_calibration():
    state["calibrating"] = True
    push_status()
    push({"type": "toast", "level": "info", "text": "Eye calibration is opening. Follow the dots, then the nine points."})
    try:
        r = subprocess.run([sys.executable, os.path.join(ROOT, "gaze_calibrate.py")], cwd=ROOT, timeout=600,
                           capture_output=True, text=True)
        if r.returncode == 0 and gaze.load_saved():
            gaze.start()
            push({"type": "toast", "level": "ok", "text": "Eye tracking calibrated and on."})
        else:
            push({"type": "toast", "level": "err", "text": "Calibration did not finish. " + (r.stderr or "")[-120:]})
    except Exception as e:
        push({"type": "toast", "level": "err", "text": f"Calibration failed: {e}"})
    finally:
        state["calibrating"] = False
        push_status()


def set_owner(address: str):
    """Bring-your-own-wallet: the connected MetaMask account becomes the owner of this device's vault."""
    from web3 import Web3
    if not Web3.is_address(address):
        push({"type": "toast", "level": "err", "text": "That owner address is not valid."})
        return
    wl.OWNER = Web3.to_checksum_address(address)
    wl.FAMILY_MODE = wl.OWNER != wl._acct.address
    try:  # remember it across restarts
        lines = open(ENV_PATH).read().splitlines() if os.path.exists(ENV_PATH) else []
        lines = [ln for ln in lines if not ln.startswith("VAULT_OWNER=")] + [f"VAULT_OWNER={wl.OWNER}"]
        open(ENV_PATH, "w").write("\n".join(lines) + "\n")
    except OSError:
        pass
    push({"type": "toast", "level": "ok", "text": f"{wl.OWNER[:6]}…{wl.OWNER[-4:]} is now the owner of this device."})
    push_status()


# ── HTTP / WebSocket ─────────────────────────────────────────────────────────
@web.middleware
async def no_cache(request, handler):
    resp = await handler(request)
    resp.headers["Cache-Control"] = "no-store"
    return resp


async def ws_handler(request):
    origin = request.headers.get("Origin")
    if origin and origin not in allowed_origins:  # blocks other websites from driving the assistant
        return web.Response(status=403, text="forbidden origin")
    ws = web.WebSocketResponse(heartbeat=20)
    await ws.prepare(request)
    clients.add(ws)
    await ws.send_str(json.dumps({"type": "state", "value": state["voice"]}))
    push_status()
    try:
        async for m in ws:
            if m.type != WSMsgType.TEXT:
                continue
            try:
                msg = json.loads(m.data)
            except json.JSONDecodeError:
                continue
            await asyncio.get_running_loop().run_in_executor(None, dispatch, msg)
    finally:
        clients.discard(ws)
    return ws


def dispatch(msg: dict):
    t = msg.get("type")
    if t == "say":
        text = str(msg.get("text", "")).strip()[:500]
        if text:
            if agents.gate.handle_utterance(text):
                on_event("User", "say", text)
            elif not agents.gate.active:
                submit(text)  # typed commands run immediately (no merge delay)
    elif t == "mic":
        if msg.get("on") and not state["listening"]:
            voice.start()
            state["listening"] = True
        elif not msg.get("on") and state["listening"]:
            voice.stop()
            state["listening"] = False
            on_voice_state("idle")
        push_status()
    elif t == "confirm":
        agents.gate.resolve(bool(msg.get("decision")), "button")
    elif t == "mode":
        agents.set_mode("transcribe" if msg.get("value") == "transcribe" else "assistant")
    elif t == "gaze":
        if msg.get("on") and gaze.calibrated:
            gaze.start()
        elif not msg.get("on"):
            gaze.stop()
        elif not gaze.calibrated:
            push({"type": "toast", "level": "warn", "text": "Calibrate eye tracking first."})
        time.sleep(0.2)
        push_status()
    elif t == "calibrate":
        if not state["calibrating"]:
            threading.Thread(target=run_calibration, daemon=True).start()
    elif t == "scam":
        threading.Thread(target=run_scam, daemon=True).start()
    elif t == "refresh":
        push_status()
    elif t == "set_owner":
        set_owner(str(msg.get("address", "")))


async def index(request):
    return web.FileResponse(os.path.join(UI_DIR, "index.html"))


async def api_status(request):
    s = await asyncio.get_running_loop().run_in_executor(None, build_status)
    return web.json_response(s)


async def periodic(app):
    """Keep balances fresh and show 'speaking' while the TTS talks."""
    async def tick():
        last_speaking, n = False, 0
        while True:
            await asyncio.sleep(0.15)
            sp = bool(voice and voice.is_speaking())
            if sp != last_speaking:
                last_speaking = sp
                push({"type": "state", "value": "speaking" if sp else ("listening" if state["listening"] else "idle")})
            n += 1
            if n % 200 == 0:  # about every 30 s
                push_status()
    task = asyncio.create_task(tick())
    yield
    task.cancel()


def make_app(port: int):
    app = web.Application(middlewares=[no_cache])
    allowed_origins.update({f"http://127.0.0.1:{port}", f"http://localhost:{port}"})
    app.router.add_get("/", index)
    app.router.add_get("/ws", ws_handler)
    app.router.add_get("/api/status", api_status)
    app.router.add_static("/", UI_DIR, show_index=False)
    app.cleanup_ctx.append(periodic)
    return app


def main():
    global loop, voice, gaze
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()

    voice = Voice(handle_utterance, on_state=on_voice_state, on_level=on_level)
    gaze = GazeController(on_event=lambda m: on_event("System", "tool", m))
    try:
        gaze.load_saved()
    except Exception:
        pass
    agents.bus.on_event = on_event
    agents.bus.speak = speak
    agents.bus.is_speaking = voice.is_speaking
    agents.bus.on_confirm = lambda payload: push({"type": "confirm", **payload})
    agents.bus.on_tx = lambda payload: push({"type": "tx", **payload})
    agents.on_mode_change = lambda m: push_status()

    if agents.BACKEND == "local":
        from server import server as llama
        print("Starting local Gemma 4 server…")
        llama.start()

    app = make_app(a.port)
    url = f"http://127.0.0.1:{a.port}"

    async def run():
        global loop
        loop = asyncio.get_running_loop()
        runner = web.AppRunner(app)
        await runner.setup()
        await web.TCPSite(runner, "127.0.0.1", a.port).start()
        print(f"Halo is running at {url}  (Ctrl+C to stop)")
        if not a.no_browser:
            webbrowser.open(url)
        await asyncio.Event().wait()

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        pass
    finally:
        voice.stop()
        gaze.stop()


if __name__ == "__main__":
    main()
