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
                dur = len(audio) / SAMPLE_RATE
                sd.stop()
                sd.play(audio, SAMPLE_RATE)  # sounddevice manages the stream: far more robust than hand-opened streams
                t0 = time.time()
                while (el := time.time() - t0) < dur + 0.25 and not self._stop.is_set():
                    i = min(len(audio) - 1, int(el * SAMPLE_RATE))
                    w = audio[i:i + SAMPLE_RATE // 50].astype(np.float32)
                    if len(w):
                        self.on_level(min(1.0, float(np.sqrt(np.mean(w ** 2))) / 9000))
                    time.sleep(0.04)
                if self._stop.is_set():
                    sd.stop()
            except Exception as e:
                print(f"TTS playback error: {e}")
                fallback()
                return
            finally:
                self.on_level(0.0)
                on_done(None)
        threading.Thread(target=run, daemon=True).start()

    def stop(self):
        self._stop.set()


class OpenAITTS(ElevenTTS):
    """OpenAI gpt-4o-mini-tts: natural, warm, multilingual; uses the same OPENAI_API_KEY as everything else."""
    name = "openai"
    STYLE = ("Warm, calm and friendly, like a kind helper. Natural conversational pace, slightly brisk. "
             "Never robotic and never slow.")

    def __init__(self, voice: str, on_level=None):
        super().__init__("", voice, os.getenv("OPENAI_TTS_MODEL", "tts-1"), 10**9, on_level)
        from openai import OpenAI
        self.client = OpenAI(timeout=20.0, max_retries=1)

    def _fetch(self, text: str) -> bytes:
        if text in self.cache:
            return self.cache[text]
        try:
            kw = {"instructions": self.STYLE} if "4o" in self.model else {"speed": float(os.getenv("OPENAI_TTS_SPEED", "1.1"))}
            r = self.client.audio.speech.create(model=self.model, voice=self.voice_id, input=text, response_format="pcm", **kw)
            pcm = r.read() if hasattr(r, "read") else r.content
        except Exception as e:
            msg = str(e)
            if any(x in msg for x in ("401", "403", "404", "invalid_api_key", "model_not_found")):
                self.disabled_reason = f"OpenAI TTS unavailable: {msg[:60]}"
            raise
        if len(pcm) < 2000:
            raise RuntimeError("empty audio")
        if len(self.cache) < 80:
            self.cache[text] = pcm
        return pcm


def build_engines(on_level=None):
    """Returns (primary, fallback). Primary is ElevenLabs when a key is configured and TTS_ENGINE allows it."""
    system = SystemTTS()
    key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if key and os.getenv("TTS_ENGINE", "openai") == "elevenlabs":
        eleven = ElevenTTS(
            key, os.getenv("ELEVEN_VOICE_ID", "21m00Tcm4TlvDq8ikWAM"),  # "Rachel": warm, clear premade voice
            os.getenv("ELEVEN_MODEL", "eleven_flash_v2_5"), int(os.getenv("ELEVEN_MAX_CHARS", "6000")), on_level)
        return eleven, system
    if os.getenv("OPENAI_API_KEY") and os.getenv("TTS_ENGINE", "openai") != "system":
        return OpenAITTS(os.getenv("OPENAI_TTS_VOICE", "nova"), on_level), system
    return system, system
