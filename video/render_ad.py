"""Render the Halo ad (video/ad.html) to MP4 with voiceover + generated soundtrack.
   python video/render_ad.py            # voiceover: ElevenLabs if ELEVENLABS_API_KEY works, else macOS voices
   python video/render_ad.py --system   # force macOS voices
Output: video/out/halo_ad.mp4 (1280x720, 30 fps, ~40 s)"""
import os, subprocess, sys, tempfile, time, wave
import numpy as np
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
from dotenv import load_dotenv; load_dotenv(os.path.join(ROOT, ".env"))
import imageio_ffmpeg, requests, cdp

FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
OUT = os.path.join(ROOT, "video", "out"); os.makedirs(OUT, exist_ok=True)
FPS, DUR, SR = 30, 40.0, 44100
FORCE_SYSTEM = "--system" in sys.argv

# (start seconds, speaker, text)
VO = [
    (0.9,  "narrator", "Ramesh has guarded this gate for twenty years. He uses WhatsApp and UPI every day. But a computer? Never."),
    (6.9,  "narrator", "One evening, a call. His son has had an accident. Send money, now."),
    (13.9, "ramesh",   "Halo, bhej do."),
    (15.6, "narrator", "Halo reads it back, and waits."),
    (18.7, "ramesh",   "Haan."),
    (20.9, "narrator", "But the rules his family set on Monad step in. Over the limit. Rejected."),
    (24.7, "halo",     "This is above your family's limit. Nothing was sent."),
    (28.7, "narrator", "Halo calls his son instead. The scammer got nothing."),
    (33.6, "halo",     "Halo. Personal AI agents, for everyone the AI age forgot."),
]
SAY = {"narrator": ("Rishi", 160), "halo": ("Samantha", 168), "ramesh": ("Aman", 165)}
ELEVEN = {"narrator": os.getenv("ELEVEN_NARRATOR", "pNInz6obpgDQGcFmaJgB"),   # Adam
          "halo": os.getenv("ELEVEN_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"),       # Rachel
          "ramesh": os.getenv("ELEVEN_RAMESH", "ErXwobaYiN019PkySvjV")}       # Antoni

def read_wav(path):
    with wave.open(path) as w:
        a = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768
        return a.reshape(-1, w.getnchannels()).mean(axis=1), w.getframerate()

def tts_say(text, speaker, path):
    v, r = SAY[speaker]
    aiff = path + ".aiff"
    subprocess.run(["say", "-v", v, "-r", str(r), "-o", aiff, text], check=True)
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-i", aiff, "-ar", str(SR), "-ac", "1", path], check=True)

def tts_eleven(text, speaker, path):
    r = requests.post(f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN[speaker]}",
        params={"output_format": "pcm_24000"}, headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]},
        json={"text": text, "model_id": os.getenv("ELEVEN_MODEL_VIDEO", "eleven_multilingual_v2"),
              "voice_settings": {"stability": 0.5, "similarity_boost": 0.8, "style": 0.3}}, timeout=60)
    r.raise_for_status()
    raw = path + ".pcm"; open(raw, "wb").write(r.content)
    subprocess.run([FFMPEG, "-y", "-loglevel", "error", "-f", "s16le", "-ar", "24000", "-ac", "1", "-i", raw, "-ar", str(SR), path], check=True)

def make_voice(use_eleven):
    n = int(DUR * SR); vo = np.zeros(n, np.float32); tmp = tempfile.mkdtemp()
    for i, (t0, spk, text) in enumerate(VO):
        p = os.path.join(tmp, f"{i}.wav")
        (tts_eleven if use_eleven else tts_say)(text, spk, p)
        a, sr = read_wav(p); s = int(t0 * SR); a = a[: n - s]
        vo[s:s + len(a)] += a * (0.95 if spk != "ramesh" else 0.8)
        print(f"   VO {t0:5.1f}s  {spk:8} {len(a)/SR:4.1f}s  {text[:50]}")
    return vo

def make_music(vo):
    n = int(DUR * SR); t = np.arange(n) / SR; m = np.zeros(n, np.float32)
    notes = lambda *hz: hz
    prog = [(0, 20, notes(110, 164.8, 220, 261.6, 329.6)),        # Am: tense
            (20, 28, notes(87.3, 130.8, 174.6, 220, 261.6)),      # F
            (28, 33.5, notes(130.8, 196, 261.6, 329.6, 392)),     # C: relief
            (33.5, 40, notes(98, 146.8, 196, 246.9, 392))]        # G -> resolve
    for a, b, hz in prog:
        i0, i1 = int(a * SR), int(min(b, DUR) * SR); seg = t[i0:i1] - a
        env = np.clip(seg / 2.0, 0, 1) * np.clip((b - a - seg) / 2.0, 0, 1)
        for f in hz:
            m[i0:i1] += (np.sin(2 * np.pi * f * seg) + .35 * np.sin(2 * np.pi * 2 * f * seg + 1) + .12 * np.sin(2 * np.pi * 3 * f * seg)) * env * (0.045 / len(hz) * 5)
    for hb in np.arange(7.0, 20.0, 0.95):                          # heartbeat while he panics
        for off, g in ((0, 1.0), (0.22, 0.6)):
            i = int((hb + off) * SR); L = int(0.25 * SR)
            if i + L < n: m[i:i + L] += np.sin(2 * np.pi * 52 * np.arange(L) / SR) * np.exp(-np.arange(L) / (0.05 * SR)) * 0.30 * g
    for k, f in enumerate((784, 1046.5, 1318.5)):                  # relief chime
        i = int((28.6 + k * 0.16) * SR); L = int(1.4 * SR)
        if i + L < n: m[i:i + L] += np.sin(2 * np.pi * f * np.arange(L) / SR) * np.exp(-np.arange(L) / (0.45 * SR)) * 0.10
    env = np.abs(vo); k = int(0.25 * SR); env = np.convolve(env, np.ones(k) / k, mode="same")
    duck = 1.0 - 0.6 * np.clip(env * 12, 0, 1)                     # duck the music under speech
    m *= duck; m *= np.clip(t / 1.5, 0, 1) * np.clip((DUR - t) / 2.0, 0, 1)
    return m

def main():
    use_eleven = False
    if not FORCE_SYSTEM and os.getenv("ELEVENLABS_API_KEY"):
        try:
            r = requests.get("https://api.elevenlabs.io/v1/user", headers={"xi-api-key": os.environ["ELEVENLABS_API_KEY"]}, timeout=15)
            use_eleven = r.ok
        except Exception:
            pass
    print("Voiceover engine:", "ElevenLabs" if use_eleven else "macOS voices")
    vo = make_voice(use_eleven); music = make_music(vo)
    mix = np.clip(vo * 1.0 + music * 1.0, -1, 1)
    wavp = os.path.join(OUT, "ad_audio.wav")
    with wave.open(wavp, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes((mix * 32767).astype(np.int16).tobytes())
    mp4 = os.path.join(OUT, "halo_ad.mp4")
    ff = subprocess.Popen([FFMPEG, "-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", str(FPS), "-i", "-", "-i", wavp,
                           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18", "-preset", "medium", "-c:a", "aac", "-b:a", "192k",
                           "-shortest", "-movflags", "+faststart", mp4], stdin=subprocess.PIPE)
    b = cdp.Chrome(1280, 720); t0 = time.time()
    try:
        b.open("file://" + os.path.join(ROOT, "video", "ad.html"), settle=1)
        import base64
        for f in range(int(DUR * FPS)):
            b.eval(f"__setTime({f / FPS:.4f})")
            shot = b.send("Page.captureScreenshot", format="jpeg", quality=88)
            ff.stdin.write(base64.b64decode(shot["data"]))
            if f % 150 == 0: print(f"   frame {f}/{int(DUR*FPS)}  ({time.time()-t0:.0f}s)")
    finally:
        b.close(); ff.stdin.close(); ff.wait()
    print("DONE:", mp4, f"{os.path.getsize(mp4)/1e6:.1f} MB")

main()
