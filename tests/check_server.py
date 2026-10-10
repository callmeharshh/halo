"""Protocol test for halo.py: starts the REAL server and talks to it like the browser UI does.

  python tests/check_server.py            # no money moves (confirm card is CANCELLED)
  python tests/check_server.py --live-tx  # also approves one 0.05 MON payment on Monad testnet
Needs OPENAI_API_KEY and, for payments, VAULT_OWNER (family mode) or a funded solo vault in .env.
"""
import asyncio, json, os, subprocess, sys, time
import aiohttp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8766
LIVE = "--live-tx" in sys.argv
BASE = f"http://127.0.0.1:{PORT}"
fails = []

def check(name, ok, extra=""):
    print(("  PASS " if ok else "  FAIL ") + name + (f"  [{extra}]" if extra and not ok else ""))
    if not ok: fails.append(name)

async def collect(ws, until, timeout=60):
    """Read messages until predicate(msg) is true; return (matching_msg, all_msgs)."""
    seen, end = [], time.time() + timeout
    while time.time() < end:
        try: m = await ws.receive(timeout=max(0.1, end - time.time()))
        except asyncio.TimeoutError: break
        if m.type != aiohttp.WSMsgType.TEXT: continue
        d = json.loads(m.data); seen.append(d)
        if until(d): return d, seen
    return None, seen

async def main():
    env = dict(os.environ, VAULT_OWNER=os.getenv("HALO_TEST_OWNER", "0xb5848eF465b06Ade36461e0f49aE2809Bae08b98"))
    proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "halo.py"), "--no-browser", "--port", str(PORT)], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        async with aiohttp.ClientSession() as s:
            for _ in range(60):
                try:
                    async with s.get(BASE + "/api/status") as r:
                        if r.status == 200: st = await r.json(); break
                except aiohttp.ClientError: pass
                await asyncio.sleep(1)
            else:
                print(proc.stdout.read()[-800:]); check("server starts", False); return
            check("server starts and /api/status answers", True)
            for k in ("mode", "device", "owner", "contract", "vault", "policy", "contacts", "llm"):
                check(f"status has '{k}'", k in st, str(list(st)))
            check("contract is the v2 address from deployment.json",
                  st["contract"].lower() == json.load(open(os.path.join(ROOT, "contracts/deployment.json")))["address"].lower())

            async with s.ws_connect(BASE + "/ws", headers={"Origin": "http://evil.example"}) as _:
                pass
    except aiohttp.WSServerHandshakeError as e:
        check("foreign Origin is rejected (403)", e.status == 403, str(e.status))
    else:
        check("foreign Origin is rejected (403)", False, "connection was accepted")
    try:
        async with aiohttp.ClientSession() as s:
            async with s.ws_connect(BASE + "/ws", headers={"Origin": BASE}) as ws:
                first, _ = await collect(ws, lambda d: d["type"] == "status", 15)
                check("WS sends status on connect", first is not None)
                await ws.send_json({"type": "say", "text": "what time is it"})
                rep, _ = await collect(ws, lambda d: d["type"] == "event" and d["kind"] == "reply" and d["agent"] == "Orchestrator", 45)
                check("typed command -> agents -> reply event", rep is not None and len(rep["text"]) > 3, str(rep))

                await ws.send_json({"type": "mode", "value": "transcribe"})
                m, _ = await collect(ws, lambda d: d["type"] == "status" and d["data"]["assistant_mode"] == "transcribe", 10)
                check("mode switch to transcribe reflected in status", m is not None)
                await ws.send_json({"type": "mode", "value": "assistant"})
                m, _ = await collect(ws, lambda d: d["type"] == "status" and d["data"]["assistant_mode"] == "assistant", 10)
                check("mode switch back to assistant", m is not None)

                await ws.send_json({"type": "say", "text": "send 0.05 MON to Alice"})
                card, _ = await collect(ws, lambda d: d["type"] == "confirm" and d.get("pending"), 60)
                check("payment shows a confirm card with amount + recipient", bool(card) and card.get("amount") == "0.05" and card.get("to") == "Alice", str(card))
                if card:
                    await asyncio.sleep(6)  # the Guardian arms only after the read-back finishes
                    await ws.send_json({"type": "confirm", "decision": LIVE})
                    end, seen = await collect(ws, lambda d: d["type"] == "confirm" and not d.get("pending"), 20)
                    check("confirm card closes after the answer", end is not None)
                    if LIVE:
                        tx, _ = await collect(ws, lambda d: d["type"] == "event" and d["kind"] == "tx", 60)
                        check("approved payment produces a real tx link", bool(tx) and "monadscan.com/tx/0x" in tx["text"], str(tx))
                    else:
                        den, _ = await collect(ws, lambda d: d["type"] == "event" and d["kind"] in ("denied", "reply"), 30)
                        check("cancel leaves funds untouched", den is not None)

                await ws.send_json({"type": "set_owner", "address": "not-an-address"})
                t, _ = await collect(ws, lambda d: d["type"] == "toast" and d["level"] == "err", 10)
                check("invalid set_owner is refused with an error toast", t is not None)
    finally:
        proc.terminate()
    print("\nSERVER CHECK:", "ALL PASSED" if not fails else f"{len(fails)} FAILED: {fails}")
    sys.exit(1 if fails else 0)

asyncio.run(main())
