"""Dev-only mock of the Halo backend: serves ui/ and emulates the /ws protocol.
Run:  python dev_mock_server.py [--port 8799] [--no-loop]
Test hooks: GET /dev/last (recorded client messages), say "pay"/"send" to raise a confirm card."""
import argparse, asyncio, json, time
from pathlib import Path
from aiohttp import web, WSMsgType

UI = Path(__file__).parent
DEVICE = "0xF54224dcD8eCD1D38c59a9e38Da333f3939402Ed"
STATUS = {
    "mode": "family", "device": DEVICE, "owner": "", "vault": "0.150", "wallet": "1.03",
    "policy": {"configured": True, "max_per_tx": "0.1", "daily_limit": "0.3", "trusted_only": True, "paused": False, "agent_ok": True},
    "contacts": [{"name": "alice", "address": "0x7321000000000000000000000000000000009b39"}],
    "llm": "gpt-4.1 (cloud)", "listening": False, "assistant_mode": "assistant",
    "gaze": {"calibrated": False, "on": False},
    "contract": "0x3e89164abbc8852955F179D964B696a4b713418A", "explorer": "https://testnet.monadscan.com",
}
CLIENTS, RECEIVED, PENDING = set(), [], {"fut": None}


async def bcast(m):
    for w in list(CLIENTS):
        try: await w.send_str(json.dumps(m))
        except Exception: CLIENTS.discard(w)

async def ev(agent, kind, text, d=0.5):
    await bcast({"type": "event", "agent": agent, "kind": kind, "text": text}); await asyncio.sleep(d)

async def state(v, d=1.2):
    await bcast({"type": "state", "value": v}); await asyncio.sleep(d)

async def status(): await bcast({"type": "status", "data": STATUS})

async def chat(text="What is the weather like today?"):
    await state("listening", 0.8); await state("hearing", 0.8)
    await ev("User", "say", text)
    await state("thinking", 0.4)
    await ev("Orchestrator", "route", "chat -> answer directly")
    await ev("System", "tool", "weather lookup")
    await state("speaking", 0.3)
    await ev("Orchestrator", "reply", "It is sunny and 28 degrees. A lovely day for a walk.", 3.5)
    await state("idle", 0.1)

async def pay():
    await state("hearing", 0.6)
    await ev("User", "say", "Send 0.05 to Alice")
    await state("thinking", 0.3)
    await ev("Orchestrator", "route", "payment -> Wallet agent")
    await ev("Guardian", "review", "Alice is a trusted contact. 0.05 is under the 0.1 limit.")
    await ev("Wallet", "ask", "Asking for your confirmation")
    fut = asyncio.get_event_loop().create_future(); PENDING["fut"] = fut
    await bcast({"type": "confirm", "pending": True, "text": "Send 0.05 MON to Alice (0x7321…9b39).", "amount": "0.05", "to": "Alice", "address": "0x7321…9b39", "note": "", "timeout": 25})
    await state("speaking", 0)
    try: ok = await asyncio.wait_for(fut, 25)
    except asyncio.TimeoutError: ok = None
    PENDING["fut"] = None
    await bcast({"type": "confirm", "pending": False})
    if ok:
        await ev("Wallet", "approved", "via button")
        await ev("Wallet", "send", "Sending 0.05 MON to Alice")
        await ev("Wallet", "tx", "https://testnet.monadscan.com/tx/0x" + "ab" * 32)
        await ev("Orchestrator", "reply", "Done. I sent 0.05 MON to Alice.", 2)
    elif ok is None:
        await ev("Guardian", "timeout", "No answer, so I cancelled the payment.")
    else:
        await ev("Guardian", "denied", "You cancelled the payment.")
        await ev("Orchestrator", "reply", "Okay, I did not send anything.", 2)
    await state("idle", 0)

async def ws_handler(req):
    ws = web.WebSocketResponse(); await ws.prepare(req); CLIENTS.add(ws)
    await ws.send_str(json.dumps({"type": "status", "data": STATUS}))
    async for m in ws:
        if m.type != WSMsgType.TEXT: continue
        try: d = json.loads(m.data)
        except ValueError: continue
        RECEIVED.append({**d, "_t": time.time()})
        t = d.get("type")
        if t == "confirm" and PENDING["fut"] and not PENDING["fut"].done(): PENDING["fut"].set_result(bool(d.get("decision")))
        elif t == "say":
            asyncio.create_task(pay() if any(w in d.get("text", "").lower() for w in ("pay", "send")) else chat(d.get("text") or ""))
        elif t == "mic": STATUS["listening"] = bool(d.get("on")); await status(); await state("listening" if d.get("on") else "idle", 0)
        elif t == "mode": STATUS["assistant_mode"] = d.get("value", "assistant"); await status()
        elif t == "gaze": STATUS["gaze"]["on"] = bool(d.get("on")); await status()
        elif t == "calibrate": STATUS["gaze"]["calibrated"] = True; await status(); await bcast({"type": "toast", "level": "ok", "text": "Eyes calibrated."})
        elif t == "scam": await bcast({"type": "toast", "level": "warn", "text": "This message looks like a scam. Do not click the link."})
        elif t == "refresh": await status()
        elif t == "set_owner":
            STATUS["owner"] = d.get("address", ""); await status()
    CLIENTS.discard(ws); return ws

async def loop():
    await asyncio.sleep(3)
    while True:
        if CLIENTS and not PENDING["fut"]:
            await chat(); await asyncio.sleep(6)
            await pay(); await asyncio.sleep(10)
        await asyncio.sleep(1)

async def last(req): return web.json_response(RECEIVED)
async def index(req): return web.FileResponse(UI / "index.html")

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--port", type=int, default=8799); ap.add_argument("--no-loop", action="store_true")
    a = ap.parse_args()
    app = web.Application()
    app.add_routes([web.get("/ws", ws_handler), web.get("/dev/last", last), web.get("/", index), web.static("/", UI)])
    if not a.no_loop:
        async def start(app): app["t"] = asyncio.create_task(loop())
        app.on_startup.append(start)
    web.run_app(app, host="127.0.0.1", port=a.port, print=lambda *_: print(f"mock on http://127.0.0.1:{a.port}/", flush=True))

if __name__ == "__main__": main()
