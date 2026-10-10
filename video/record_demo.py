"""Record a REAL demo of Halo Journeys: starts the local server (live mode), drives the page in headless Chrome, records it,
adds narration (OpenAI TTS) + captions, and performs a REAL attestation on Monad with a test wallet. Output: video/out/halo_demo.mp4
   python video/record_demo.py"""
import base64, io, os, subprocess, sys, tempfile, time, urllib.request, wave
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
from dotenv import load_dotenv; load_dotenv(os.path.join(ROOT, ".env"))
import cdp, imageio_ffmpeg
from openai import OpenAI

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe(); OUT = os.path.join(ROOT, "video", "out"); os.makedirs(OUT, exist_ok=True)
PORT = 8783; SR = 44100; KEY = os.environ["WALLET_PRIVATE_KEY"]  # device wallet (has enough gas for one attestation)
oa = OpenAI(timeout=60)
REQUEST = "3 days from Pune to Goa. I use a wheelchair. Budget about 30000 rupees. Beaches and good food, no stairs."

VO = {
  "intro":  "Planning a trip with a disability usually means hours of phone calls, because a website that says accessible can mean almost anything.",
  "ask":    "With Halo Journeys, you just say where you want to go, and what you need.",
  "search": "It researches every airport, station and hotel on the web, and keeps the source for every single fact.",
  "result": "Each fact comes with its link. And if nothing reliable is found, it says unknown, never a guess.",
  "chain":  "Then it checks Monad, where real travellers record what they actually found. This place is only web-sourced so far.",
  "attest": "So a traveller who has been there confirms it. One signature, one transaction on Monad.",
  "badge":  "And now the badge changes, for everyone who plans a trip here.",
  "end":    "Halo Journeys. Travel without guessing.",
}
def tts(key):
    p = os.path.join(OUT, f"vo_{key}.pcm")
    r = oa.audio.speech.create(model="gpt-4o-mini-tts", voice="coral", input=VO[key], response_format="pcm",
        instructions="Calm, warm, human narrator for a short product film. Natural pace, gentle emphasis, never robotic.")
    open(p, "wb").write(r.read())
    wavp = os.path.join(OUT, f"vo_{key}.wav")
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", p, "-ar", str(SR), wavp], check=True)
    with wave.open(wavp) as w: a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    return a
print("generating narration…"); AUD = {k: tts(k) for k in VO}; print({k: round(len(v) / SR, 1) for k, v in AUD.items()})

srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "travel", "server.py"), "--no-browser", "--port", str(PORT)], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
frames, marks = [], {}
b = None
def grab():
    s = b.send("Page.captureScreenshot", format="jpeg", quality=82); frames.append((time.time(), base64.b64decode(s["data"])))
def hold(sec):
    end = time.time() + sec
    while time.time() < end: grab()
def wait(js, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        if b.eval(js): return True
        grab()
    return False
def caption(text):
    import json as _j
    js = ("(()=>{let c=document.getElementById('__cap');if(!c){c=document.createElement('div');c.id='__cap';"
          "c.style.cssText='position:fixed;left:50%;top:12px;transform:translateX(-50%);max-width:760px;padding:12px 24px;border-radius:14px;"
          "background:rgba(7,7,13,.82);color:#fff;font:600 22px/1.3 system-ui;text-align:center;z-index:99999;backdrop-filter:blur(6px);"
          "border:1px solid rgba(255,255,255,.15)';document.body.appendChild(c)}c.textContent=__T__;c.style.opacity=__O__})()")
    b.eval(js.replace("__T__", _j.dumps(text)).replace("__O__", "1" if text else "0"))
def say(key, minimum=0):
    marks[key] = frames[-1][0] if frames else time.time()
    return max(minimum, len(AUD[key]) / SR + 0.4)
try:
    for _ in range(60):
        try: urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/config", timeout=3); break
        except Exception: time.sleep(1)
    b = cdp.Chrome(1280, 720)
    b.send("Emulation.setDeviceMetricsOverride", width=1280, height=720, deviceScaleFactor=1, mobile=False)
    b.open(f"http://127.0.0.1:{PORT}/journeys.html", preload=cdp.mock_wallet(KEY), settle=2.5)
    grab()
    # 1 intro
    caption("Halo Journeys · an AI travel agent for travellers with disabilities"); d = say("intro"); hold(d)
    # 2 ask
    caption("Say or type your trip and your needs"); d = say("ask")
    b.eval("document.querySelector('#req').focus()")
    t0 = time.time()
    for i in range(0, len(REQUEST) + 3, 3):
        b.eval("(()=>{const e=document.querySelector('#req');e.value=%r;e.dispatchEvent(new Event('input',{bubbles:true}))})()" % REQUEST[:i]); grab()
    b.eval("(()=>{const c=[...document.querySelectorAll('#needs button, #needs label, #needs input')].find(x=>/wheelchair/i.test(x.innerText||x.value||x.getAttribute('aria-label')||''));if(c)c.click()})()")
    hold(max(0.5, d - (time.time() - t0)))
    # 3 search
    caption("It researches every place on the web, with sources"); d = say("search")
    b.eval("document.querySelector('#go').click()")
    t0 = time.time(); ok = wait("(()=>{const r=document.querySelector('#result');return r&&!r.hidden&&document.querySelectorAll('#places > *').length>0})()", 90)
    hold(max(0.2, d - (time.time() - t0)))
    # 4 result
    caption("Every fact has its source. Unknown stays unknown."); d = say("result")
    b.eval("document.querySelector('#places-h').scrollIntoView({behavior:'smooth',block:'start'})"); hold(d)
    # 5 chain
    caption("Cross-checked against real travellers, on Monad"); d = say("chain")
    b.eval("window.scrollBy({top:260,behavior:'smooth'})"); hold(d)
    # 6 attest
    caption("A traveller confirms it: one transaction on Monad"); d = say("attest")
    b.eval("[...document.querySelectorAll('#places button')].find(x=>/I have been here/i.test(x.innerText)).click()"); hold(1.2)
    b.eval("[...document.querySelectorAll('#att-feats input')].slice(0,3).forEach(i=>i.click())"); hold(0.8)
    b.eval("(()=>{const n=document.querySelector('#att-note');n.value='Step-free entrance and a ramp at the main door, confirmed on site.';n.dispatchEvent(new Event('input',{bubbles:true}))})()"); hold(0.8)
    b.eval("document.querySelector('#att-go').click()")
    t0 = time.time()
    done = wait("document.querySelector('#dlg-back').hidden || /Done\.|Could not complete/.test(document.querySelector('#att-status').innerText)", 100)
    hold(max(0.5, d - (time.time() - t0)))
    b.eval("(()=>{const x=document.querySelector('#dlg-back');if(x&&!x.hidden){const c=document.querySelector('#att-close');c&&c.click()}})()")
    # 7 badge flips
    b.eval("(()=>{const x=document.querySelector('#dlg-back');if(x&&!x.hidden){const c=document.querySelector('#att-close');c&&c.click()}})()")
    b.eval("(()=>{const a=[...document.querySelectorAll('#places > *')][0];a&&a.scrollIntoView({behavior:'smooth',block:'start'})})()")
    caption("The badge updates: 1 traveller verified"); d = say("badge")
    wait("/1 traveller verified|Community-verified|Venue-confirmed/.test(document.body.innerText)", 40); hold(d)
    # 8 end card
    b.eval("(()=>{const o=document.createElement('div');o.style.cssText='position:fixed;inset:0;z-index:100000;background:radial-gradient(900px 500px at 50% 30%,#2a1f66,#07070d);color:#fff;display:flex;flex-direction:column;align-items:center;justify-content:center;font-family:system-ui;text-align:center';o.innerHTML='<div style=\"width:96px;height:96px;border-radius:50%;border:10px solid #836EF9;box-shadow:0 0 60px #836EF9aa\"></div><div style=\"font-size:76px;font-weight:800;margin-top:22px;letter-spacing:-.03em\">Halo Journeys</div><div style=\"font-size:34px;margin-top:6px\">Travel without guessing.</div><div style=\"font-size:24px;margin-top:26px;color:#b3a6ff\">callmeharshh.github.io/halo</div><div style=\"font-size:17px;margin-top:10px;color:#a9a7c2;font-family:ui-monospace,Menlo,monospace\">AccessRegistry 0x3aaE87a4…4A7f · Monad testnet</div><div style=\"font-size:15px;margin-top:22px;color:#a9a7c2\">Inspired by Inclusive Travel Agent (Coders Beyond Borders) · built on GemGuide by Sourajit · Monad Blitz Pune V3</div>';document.body.appendChild(o)})()")
    caption(""); d = say("end"); hold(d + 1.0)
finally:
    if b: b.close()
    srv.terminate()

# ── assemble ──
t_start = frames[0][0]; total = frames[-1][0] - t_start + 1.2
track = np.zeros(int((total + 1) * SR), np.float32)
for k, t in marks.items():
    s = int((t - t_start) * SR); a = AUD[k]; track[s:s + len(a)] += a[: len(track) - s]
wavp = os.path.join(OUT, "demo_audio.wav")
with wave.open(wavp, "wb") as w: w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes((np.clip(track, -1, 1) * 32767).astype(np.int16).tobytes())
fd = tempfile.mkdtemp(); lst = []
for i, (t, jpg) in enumerate(frames):
    open(os.path.join(fd, f"{i:05d}.jpg"), "wb").write(jpg)
    dur = (frames[i + 1][0] - t) if i + 1 < len(frames) else 1.2
    lst.append(f"file '{fd}/{i:05d}.jpg'\nduration {max(0.04, dur):.3f}")
lst.append(f"file '{fd}/{len(frames)-1:05d}.jpg'")
open(os.path.join(fd, "list.txt"), "w").write("\n".join(lst))
mp4 = os.path.join(OUT, "halo_demo.mp4")
subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", os.path.join(fd, "list.txt"), "-i", wavp,
                "-vf", "fps=30,scale=1280:720:flags=lanczos,format=yuv420p", "-c:v", "libx264", "-crf", "19", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", mp4], check=True)
print("DONE:", mp4, f"{os.path.getsize(mp4)/1e6:.1f} MB, {total:.0f}s, {len(frames)} frames")
