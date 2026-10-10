"""Text-to-speech engines for Halo: ElevenLabs (streaming, natural, multilingual) with automatic fallback to macOS `say`.

Design goals: never block the demo. Any ElevenLabs failure (bad key, quota, network) silently falls back to `say`;
a character budget protects a small quota; repeated phrases (e.g. "Say confirm, or cancel.") are cached.
"""
import os
import re
import subprocess
import threading
import time

import numpy as np
import requests
import sounddevice as sd

SAMPLE_RATE = 24000


class SystemTTS:
    """macOS `say` (Indian-English Rishi, Hindi Lekha)."""
    name = "system"

    def __init__(self, voice="Rishi", rate=175):
        self.voice, self.rate = voice, rate
        self.proc = None

    def speak(self, text: str, on_done):
        voice = "Lekha" if re.search(r"[ऀ-ॿ]", text) else self.voice
        self.proc = subprocess.Popen(["say", "-v", voice, "-r", str(self.rate), text])
        threading.Thread(target=lambda p=self.proc: (p.wait(), on_done(p)), daemon=True).start()

    def stop(self):
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()


class ElevenTTS:
    """ElevenLabs streaming TTS, played through sounddevice as raw PCM (no audio decoder needed)."""
    name = "elevenlabs"

    def __init__(self, api_key: str, voice_id: str, model: str, max_chars: int, on_level=None):
        self.key, self.voice_id, self.model = api_key, voice_id, model
        self.max_chars, self.used = max_chars, 0
        self.disabled_reason: str | None = None
        self.cache: dict[str, bytes] = {}
        self._stop = threading.Event()
        self.on_level = on_level or (lambda v: None)
        self.failures = 0

    @property
    def available(self) -> bool:
        return self.disabled_reason is None

    def _fetch(self, text: str) -> bytes:
        """Return the complete PCM for `text` (cached). Raises on any failure."""
        if text in self.cache:
            return self.cache[text]
        if self.used + len(text) > self.max_chars:
            raise RuntimeError("character budget reached")
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{self.voice_id}/stream",
            params={"output_format": f"pcm_{SAMPLE_RATE}"},
            headers={"xi-api-key": self.key, "content-type": "application/json"},
            json={"text": text, "model_id": self.model,
                  "voice_settings": {"stability": 0.45, "similarity_boost": 0.8, "style": 0.25, "use_speaker_boost": True}},
            timeout=20, stream=True)
        if r.status_code in (400, 401, 403, 404):  # bad key / key id pasted instead of key / unknown voice
            self.disabled_reason = f"request rejected (HTTP {r.status_code}): check ELEVENLABS_API_KEY (starts with sk_) and ELEVEN_VOICE_ID"
            raise RuntimeError(self.disabled_reason)
        if r.status_code == 402 or r.status_code == 429:
            self.disabled_reason = "quota or rate limit"
            raise RuntimeError(self.disabled_reason)
        r.raise_for_status()
        pcm = b"".join(r.iter_content(8192))
        if len(pcm) < 2000:
            raise RuntimeError("empty audio")
        self.used += len(text)
        if len(self.cache) < 60:
            self.cache[text] = pcm
        return pcm

    def speak(self, text: str, on_done, fallback):
        """Play `text`; on any failure call fallback() so the user still hears something."""
        def run():
            self._stop.clear()
            try:
                pcm = self._fetch(text)
            except Exception as e:
                self.failures += 1
                if self.failures >= 3 and self.disabled_reason is None:
                    self.disabled_reason = f"repeated errors ({str(e)[:40]})"
                fallback()
                return
            try:
                audio = np.frombuffer(pcm, dtype=np.int16)
                block = SAMPLE_RATE // 50  # 20 ms
                with sd.OutputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16") as out:
                    for i in range(0, len(audio), block):
                        if self._stop.is_set():
                            break
                        chunk = audio[i:i + block]
                        out.write(chunk.reshape(-1, 1))
                        if i % (block * 2) == 0:
                            self.on_level(min(1.0, float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2))) / 9000))
            except Exception:
                pass
            finally:
                self.on_level(0.0)
                on_done(None)
        threading.Thread(target=run, daemon=True).start()

    def stop(self):
        self._stop.set()


def build_engines(on_level=None):
    """Returns (primary, fallback). Primary is ElevenLabs when a key is configured and TTS_ENGINE allows it."""
    system = SystemTTS()
    key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if key and os.getenv("TTS_ENGINE", "elevenlabs") != "system":
        eleven = ElevenTTS(
            key, os.getenv("ELEVEN_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"),  # "Rachel": warm, clear premade voice
            os.getenv("ELEVEN_MODEL", "eleven_flash_v2_5"), int(os.getenv("ELEVEN_MAX_CHARS", "6000")), on_level)
        return eleven, system
    return system, system
