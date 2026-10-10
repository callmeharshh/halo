"""Halo preflight. Run before every demo:  python doctor.py
Checks keys, network, contract, family vault, microphone, camera, screen capture, accessibility and voices."""
import json, os, platform, shutil, socket, subprocess, sys, time
ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, ".env"))

res = {"ok": 0, "warn": 0, "bad": 0}
def row(level, name, hint=""):
    icon = {"ok": "✅", "warn": "⚠️ ", "bad": "❌"}[level]
    res[level] += 1
    print(f"{icon} {name}" + (f"\n     → {hint}" if hint and level != "ok" else ""))
def section(t): print(f"\n── {t}")

section("Setup")
row("ok" if sys.version_info >= (3, 11) else "bad", f"Python {platform.python_version()}", "Use Python 3.11-3.13")
row("ok" if os.path.exists(os.path.join(ROOT, ".env")) else "bad", ".env present", "cp .env.example .env and fill it in")
row("ok" if os.getenv("OPENAI_API_KEY", "").startswith("sk-") else "bad", "OPENAI_API_KEY set", "add it to .env")
row("ok" if len(os.getenv("WALLET_PRIVATE_KEY", "").replace("0x", "")) == 64 else "bad", "device wallet key set", "add a THROWAWAY testnet key to .env")
row("ok" if os.getenv("OPENAI_MODEL", "gpt-4.1") == "gpt-4.1" else "warn", f"LLM model {os.getenv('OPENAI_MODEL', 'gpt-4.1')}", "gpt-4.1 is the fast, tested default")

section("AI (OpenAI)")
try:
    from openai import OpenAI
    t = time.time()
    r = OpenAI(timeout=15).chat.completions.create(model=os.getenv("OPENAI_MODEL", "gpt-4.1"), messages=[{"role": "user", "content": "say ok"}], max_completion_tokens=5)
    row("ok", f"LLM answers in {time.time()-t:.1f}s")
except Exception as e:
    row("bad", "LLM call failed", str(e)[:100])

section("Monad network + contract")
try:
    import wallet as wl
    row("ok" if wl.with_retry(lambda: wl.w3.eth.chain_id) == 10143 else "bad", f"Monad testnet reachable via {wl.w3.provider.endpoint_uri}")
    row("ok" if len(wl.with_retry(lambda: wl.w3.eth.get_code(wl.VAULT_ADDRESS))) > 1000 else "bad", f"GuardVault live at {wl.VAULT_ADDRESS[:10]}…")
    gas = float(wl.balance())
    row("ok" if gas >= 0.02 else "bad", f"device wallet {wl.address()[:8]}… has {gas:.3f} MON for gas", "fund it at https://faucet.monad.xyz")
    pol = wl.policy()
    mode = "FAMILY (owner " + wl.OWNER[:8] + "…)" if wl.FAMILY_MODE else "SOLO"
    print(f"   mode: {mode}")
    row("ok" if pol["configured"] else "bad", "owner rules are set", "open the Family Console and save rules (or run setup_vault.py in solo mode)")
    row("ok" if pol["agent_ok"] else "bad", "this device is the approved agent", "Family Console → Approve this device")
    row("ok" if not pol["paused"] else "bad", "payments not paused", "Family Console → Resume payments")
    vb = float(wl.vault_balance())
    row("ok" if vb >= 0.3 else ("warn" if vb >= 0.1 else "bad"), f"vault holds {vb:.3f} MON", "deposit more in the Family Console")
    row("ok" if len(wl.contact_book()) > 0 else "warn", f"{len(wl.contact_book())} trusted contact(s) saved", "add 'alice' (or your demo contact) in the Family Console")
    print(f"   limits: {pol['max_per_tx']}/tx, {pol['daily_limit']}/day, trusted-only={pol['trusted_only']}")
except Exception as e:
    row("bad", "wallet/contract check failed", str(e)[:120])

section("Microphone, camera, screen")
try:
    import sounddevice as sd
    ins = [d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0]
    row("ok" if ins else "bad", f"microphone: {ins[0] if ins else 'none'}", "plug in or enable a mic")
    import numpy as np
    with sd.InputStream(samplerate=16000, channels=1, dtype="int16") as s:
        data, _ = s.read(3200)
    lvl = int(np.abs(data).mean())
    row("ok" if lvl > 0 else "warn", f"mic permission granted (level {lvl})", "System Settings → Privacy → Microphone → allow your terminal/VS Code")
except Exception as e:
    row("bad", "microphone failed", str(e)[:100])
try:
    import cv2
    cap = cv2.VideoCapture(0); ok, _ = cap.read(); cap.release()
    row("ok" if ok else "warn", "camera works", "allow Camera for your terminal/VS Code (needed for eye tracking)")
except Exception as e:
    row("warn", "camera check failed", str(e)[:80])
try:
    import tempfile
    p = tempfile.mktemp(suffix=".png")
    r = subprocess.run(["screencapture", "-x", p], capture_output=True)
    row("ok" if r.returncode == 0 and os.path.exists(p) and os.path.getsize(p) > 1000 else "bad", "screen capture (Vision + Scam Shield)", "Privacy → Screen Recording → allow your terminal/VS Code, then restart it")
except Exception as e:
    row("bad", "screen capture failed", str(e)[:80])
try:
    from ApplicationServices import AXIsProcessTrusted
    row("ok" if AXIsProcessTrusted() else "warn", "accessibility (mouse/keyboard control)", "Privacy → Accessibility → allow your terminal/VS Code")
except Exception:
    row("warn", "accessibility could not be checked", "make sure Accessibility is allowed for your terminal/VS Code")

section("Voice, eyes, ports")
voices = subprocess.run(["say", "-v", "?"], capture_output=True, text=True).stdout
for v in ("Rishi", "Lekha"):
    row("ok" if v in voices else "warn", f"voice {v}", "System Settings → Accessibility → Spoken Content → System Voice → Manage Voices")
row("ok" if os.path.exists(os.path.join(ROOT, "gaze_lissajous.pkl")) and os.path.exists(os.path.join(ROOT, "gaze_9point.pkl")) else "warn",
    "eye-tracking calibration saved", "click Calibrate eyes in the app (about 1 minute)")
s = socket.socket(); busy = s.connect_ex(("127.0.0.1", 8765)) == 0; s.close()
row("warn" if busy else "ok", "port 8765 free" if not busy else "port 8765 is in use (Halo already running?)", "stop the other process")
row("ok" if shutil.which("python3") else "warn", "ready")

print(f"\n{'='*50}\n✅ {res['ok']} ok   ⚠️  {res['warn']} warnings   ❌ {res['bad']} problems")
print("READY TO DEMO" if res["bad"] == 0 else "FIX THE ❌ ITEMS BEFORE THE DEMO")
sys.exit(1 if res["bad"] else 0)
