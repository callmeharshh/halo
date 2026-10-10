"""Record a REAL demo of the Halo Journeys CONCIERGE: starts the local server (live mode), drives the page in headless Chrome, records it,
adds narration (OpenAI TTS) + captions, and performs a REAL attestation on Monad with a test wallet. Output: video/out/halo_concierge_demo.mp4
   python video/record_demo.py"""
import base64, io, os, subprocess, sys, tempfile, time, urllib.request, wave
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
from dotenv import load_dotenv; load_dotenv(os.path.join(ROOT, ".env"))
import cdp, imageio_ffmpeg
from openai import OpenAI

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe(); OUT = os.path.join(ROOT, "video", "out"); os.makedirs(OUT, exist_ok=True)
PORT = 8786; SR = 44100; KEY = os.environ["WALLET_PRIVATE_KEY"]  # device wallet (has enough gas for one attestation)
oa = OpenAI(timeout=60)
REQUEST = "3 days from Pune to Goa. I use a wheelchair. Budget about 30000 rupees. Beaches and good food, no stairs."

VO = {
  "intro":   "Meet the Halo Journeys concierge: fourteen specialist agents, behind one conversation.",
  "profile": "Tell it who you are once, and every answer is personalised.",
  "ask":     "Then just ask, in plain words. The concierge hands your request to the right specialist, and you can watch every hand-off.",
  "plan":    "It plans the days, researches every place on the web, keeps the source for each fact, and checks Monad for what real travellers have verified.",
  "budget":  "It estimates the cost, and shows disability-related expenses separately. These are estimates, not quotes.",
  "review":  "The safety agent reviews the plan, and flags places that nobody has verified yet, using live data from the blockchain.",
  "prep":    "Ask what to prepare, and it builds the checklist, drafts the messages to the hotel and airline for you to send, and sets up reminders. Reminders, bookings and check-in are simulated in this demo, and clearly labelled.",
  "barrier": "And when something goes wrong, like a broken lift, it offers alternatives straight away.",
  "agents":  "Fourteen agents, each with one job. Real where it matters, and honest about what is simulated.",
  "end":     "Halo Journeys. Travel without guessing.",
}
def tts(key):
    p = os.path.join(OUT, f"cvo_{key}.pcm")
    r = oa.audio.speech.create(model="gpt-4o-mini-tts", voice="coral", input=VO[key], response_format="pcm",
        instructions="Calm, warm, human narrator for a short product film. Natural pace, gentle emphasis, never robotic.")
    open(p, "wb").write(r.read())
    wavp = os.path.join(OUT, f"cvo_{key}.wav")
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", p, "-ar", str(SR), wavp], check=True)
    with wave.open(wavp) as w: a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    return a
print("generating narration…"); AUD = {k: tts(k) for k in VO}; print({k: round(len(v) / SR, 1) for k, v in AUD.items()})
M1 = "3 days from Pune to Goa. I use a wheelchair. Budget about 30000 rupees. Beaches and good food, no stairs."
M2 = "What should I prepare? Please set up the reminders and draft the messages to the hotel and the airline."
M3 = "The lift at my hotel is broken and my room is on the 4th floor. What now?"
srv = subprocess.Popen([sys.executable, os.path.join(ROOT, "travel", "server.py"), "--no-browser", "--port", str(PORT)], cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
frames, marks = [], {}
b = None
def grab():
    s = b.send("Page.captureScreenshot", format="jpeg", quality=84); frames.append((time.time(), base64.b64decode(s["data"])))
def hold(sec):
    end = time.time() + sec
    while time.time() < end: grab()
def wait(js, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        if b.eval(js): return True
        grab()
    return False
def say(key):
    marks[key] = frames[-1][0] if frames else time.time()
    return len(AUD[key]) / SR + 0.5
def typed(msg):
    for i in range(0, len(msg) + 4, 4):
        b.eval("(()=>{const e=document.querySelector('#composer-input');e.value=%r;e.dispatchEvent(new Event('input',{bubbles:true}))})()" % msg[:i]); grab()
def send(): b.eval("document.querySelector('#send').click()")
def click_chip(text):
    b.eval("(()=>{const x=[...document.querySelectorAll('#trip button, #pane-trip button')].find(e=>e.innerText.trim().toLowerCase().startsWith(%r));x&&x.click()})()" % text.lower())
try:
    for _ in range(60):
        try: urllib.request.urlopen(f"http://127.0.0.1:{PORT}/api/config", timeout=3); break
        except Exception: time.sleep(1)
    b = cdp.Chrome(1280, 720)
    b.send("Emulation.setDeviceMetricsOverride", width=1280, height=720, deviceScaleFactor=1, mobile=False)
    b.open(f"http://127.0.0.1:{PORT}/concierge.html", settle=2.5); grab()
    d = say("intro"); hold(d)
    # profile
    d = say("profile"); t0 = time.time()
    b.eval("document.querySelector('#profile-btn').click()"); hold(1.0)
    b.eval("(()=>{const n=document.querySelector('#pf-name');n.value='Priya';n.dispatchEvent(new Event('input',{bubbles:true}))})()"); hold(0.6)
    b.eval("[...document.querySelectorAll('#pf-needs input')].find(i=>i.value==='wheelchair').click()"); hold(0.8)
    b.eval("document.querySelector('#pf-save').click()"); hold(max(0.5, d - (time.time() - t0)))
    # turn 1
    d = say("ask"); t0 = time.time(); typed(M1); send(); hold(max(0.3, d - (time.time() - t0)))
    d = say("plan"); wait("/Itinerary|Day 1/i.test(document.querySelector('#arts').innerText)", 90); hold(d)
    d = say("budget"); b.eval("(()=>{const x=[...document.querySelectorAll('#trip button')].find(e=>/^budget/i.test(e.innerText.trim()));x&&x.click()})()"); hold(d)
    d = say("review"); b.eval("(()=>{const x=[...document.querySelectorAll('#trip button')].find(e=>/plan review/i.test(e.innerText.trim()));x&&x.click()})()"); hold(d)
    # turn 2
    d = say("prep"); t0 = time.time(); typed(M2); send(); wait("/checklist|reminders|messages/i.test(document.querySelector('#arts').innerText)", 60); hold(max(0.5, d - (time.time() - t0)))
    # turn 3
    d = say("barrier"); t0 = time.time(); typed(M3); send(); wait("/Alternatives right now/i.test(document.querySelector('#arts').innerText)", 60); hold(max(0.5, d - (time.time() - t0)))
    # agents tab
    d = say("agents"); b.eval("document.querySelector('#ptab-agents').click()"); hold(d)
    # end card
    b.eval("(()=>{const o=document.createElement('div');o.style.cssText='position:fixed;inset:0;z-index:100000;background:radial-gradient(900px 500px at 50% 30%,#FFFBF3,#EFE2CC);color:#1F1D24;display:flex;flex-direction:column;align-items:center;justify-content:center;font-family:\"Iowan Old Style\",Palatino,Georgia,serif;text-align:center';o.innerHTML='<div style=\"width:84px;height:84px;border-radius:50%;border:2px solid #A9875A;display:flex;align-items:center;justify-content:center;font-size:44px;color:#A9875A\">H</div><div style=\"font-size:72px;font-weight:600;margin-top:20px;letter-spacing:-.02em\">Halo Journeys</div><div style=\"font-size:32px;margin-top:6px;font-style:italic\">Travel without guessing.</div><div style=\"font:600 22px system-ui;margin-top:28px;color:#76592F\">callmeharshh.github.io/halo</div><div style=\"font:16px ui-monospace,Menlo,monospace;margin-top:10px;color:#675F50\">AccessRegistry 0x3aaE87a4…4A7f · Monad testnet</div><div style=\"font:15px system-ui;margin-top:22px;color:#675F50;max-width:900px\">Inspired by Inclusive Travel Agent (Coders Beyond Borders) and Google\u2019s inclusive-travel-agent sample · built on GemGuide by Sourajit · Monad Blitz Pune V3</div>';document.body.appendChild(o)})()")
    d = say("end"); hold(d + 1.0)
finally:
    if b: b.close()
    srv.terminate()
# ── assemble ──
t_start = frames[0][0]; total = frames[-1][0] - t_start + 1.2
track = np.zeros(int((total + 1) * SR), np.float32)
for k, t in marks.items():
    s = int((t - t_start) * SR); a = AUD[k]; track[s:s + len(a)] += a[: len(track) - s]
wavp = os.path.join(OUT, "concierge_audio.wav")
with wave.open(wavp, "wb") as w: w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes((np.clip(track, -1, 1) * 32767).astype(np.int16).tobytes())
fd = tempfile.mkdtemp(); lst = []
for i, (t, jpg) in enumerate(frames):
    open(os.path.join(fd, f"{i:05d}.jpg"), "wb").write(jpg)
    dur = (frames[i + 1][0] - t) if i + 1 < len(frames) else 1.2
    lst.append(f"file '{fd}/{i:05d}.jpg'\nduration {max(0.04, dur):.3f}")
lst.append(f"file '{fd}/{len(frames)-1:05d}.jpg'")
open(os.path.join(fd, "list.txt"), "w").write("\n".join(lst))
mp4 = os.path.join(OUT, "halo_concierge_demo.mp4")
subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", os.path.join(fd, "list.txt"), "-i", wavp,
                "-vf", "fps=30,scale=1280:720:flags=lanczos,format=yuv420p", "-c:v", "libx264", "-crf", "19", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", mp4], check=True)
print("DONE:", mp4, f"{os.path.getsize(mp4)/1e6:.1f} MB, {total:.0f}s, {len(frames)} frames")
