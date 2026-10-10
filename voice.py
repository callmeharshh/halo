"""Mac voice I/O: mic capture + WebRTC VAD + Parakeet STT, and TTS via `say`."""
import subprocess
import threading
import time

import io
import os
import queue
import re
import wave

import numpy as np
import onnx_asr
import tts
import sounddevice as sd
import webrtcvad

SAMPLE_RATE = 16000
FRAME = 480  # 30 ms @ 16 kHz, a size webrtcvad accepts


class Voice:
    def __init__(self, on_utterance, on_state=None, voice_name="Rishi", rate=175, on_level=None):
        self.on_utterance = on_utterance  # callback(text)
        self.on_state = on_state or (lambda s: None)
        self.on_level = on_level or (lambda v: None)
        self.primary_tts, self.system_tts = tts.build_engines(on_level=self.on_level)
        self.voice_name = voice_name
        self.rate = rate
        self.vad = webrtcvad.Vad(2)
        self.backend = os.getenv("STT_BACKEND", "openai")  # "openai" (fast, robust) or "parakeet" (local)
        self.stt = None
        if self.backend == "parakeet":
            self.stt = onnx_asr.load_model(
                "nemo-parakeet-tdt-0.6b-v3", quantization="int8", providers=["CPUExecutionProvider"]
            )
        else:
            from openai import OpenAI
            self._oa = OpenAI(timeout=20.0, max_retries=2)
        self._stop = threading.Event()
        self._queue: queue.Queue = queue.Queue()
        threading.Thread(target=self._worker, daemon=True).start()
        self._thread = None
        self._tts_token = None
        self._speaking_until = 0.0

    # ── TTS ──────────────────────────────────────────────────────────────
    def speak(self, text: str):
        if not text or not text.strip():
            return
        self.stop_speaking()
        self._speaking_until = time.time() + 600  # blocks mic until playback ends
        self._tts_token = object()
        token = self._tts_token

        def done(_=None):
            if token is self._tts_token:
                self._speaking_until = time.time() + 0.4  # tail so we never hear our own echo

        def via_system():
            if token is self._tts_token:
                self.system_tts.speak(text, done)

        p = self.primary_tts
        if p.name != "system" and p.available:
            p.speak(text, done, via_system)
        else:
            via_system()

    def tts_name(self) -> str:
        p = self.primary_tts
        return p.name if (p.name == "system" or p.available) else "system"

    def tts_note(self) -> str | None:
        return getattr(self.primary_tts, "disabled_reason", None)

    def stop_speaking(self):
        self._tts_token = None
        for e in (self.primary_tts, self.system_tts):
            try:
                e.stop()
            except Exception:
                pass

    def is_speaking(self) -> bool:
        return time.time() < self._speaking_until

    # ── STT ──────────────────────────────────────────────────────────────
    # Phrases speech models invent from silence/noise. Dropped when the clip is short.
    _HALLUCINATIONS = {"you", "thank you", "thanks", "thank you.", "thanks for watching", "bye", "okay", "ok", "hmm", "uh", "um", "yeah"}

    def transcribe(self, pcm: np.ndarray) -> str:
        rms = float(np.sqrt(np.mean(pcm.astype(np.float32) ** 2)))
        if rms < float(os.getenv("MIC_MIN_RMS", "180")):  # too quiet: room noise, not speech
            return ""
        # normalise: laptop mics are quiet, and recognition is noticeably better with a healthy level
        peak = float(np.max(np.abs(pcm))) or 1.0
        gain = min(8.0, 0.85 * 32767 / peak)
        pcm = np.clip(pcm.astype(np.float32) * gain, -32767, 32767).astype(np.int16)
        if self.backend == "openai":
            try:
                bio = io.BytesIO()
                with wave.open(bio, "wb") as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SAMPLE_RATE)
                    w.writeframes(pcm.tobytes())
                bio.name = "speech.wav"; bio.seek(0)
                # NO prompt (it leaks into noisy transcripts) and a FIXED language (auto-detect garbles short accented clips).
                lang = os.getenv("STT_LANGUAGE", "en")
                kwargs = {"language": lang} if lang and lang != "auto" else {}
                r = self._oa.audio.transcriptions.create(model=os.getenv("STT_MODEL", "gpt-4o-transcribe"), file=bio, **kwargs)
                text = r.text.strip()
            except Exception as e:
                print(f"STT error: {e}")
                return ""
        else:
            try:
                text = str(self.stt.recognize(pcm.astype(np.float32) / 32768.0)).strip()
            except Exception as e:
                print(f"STT error: {e}")
                return ""
        if len(pcm) < SAMPLE_RATE * 1.5 and text.lower().strip(" .!?,") in self._HALLUCINATIONS:
            return ""
        return text

    # ── listen loop ──────────────────────────────────────────────────────
    def start(self):
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self.stop_speaking()

    def _loop(self):
        buf, speaking, silent, voiced = [], False, 0, 0
        last_level = 0.0
        PRE = []  # small pre-roll so we don't clip the first syllable
        self.on_state("listening")
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=FRAME) as stream:
            while not self._stop.is_set():
                data, _ = stream.read(FRAME)
                chunk = data[:, 0].copy()
                if self.is_speaking():  # ignore mic while the assistant talks
                    buf, speaking, silent, voiced, PRE = [], False, 0, 0, []
                    continue
                now = time.time()
                if now - last_level > 0.08:  # ~12 Hz loudness for the UI orb
                    last_level = now
                    self.on_level(min(1.0, float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2))) / 5000))
                is_speech = self.vad.is_speech(chunk.tobytes(), SAMPLE_RATE)
                if not speaking:
                    PRE.append(chunk)
                    PRE = PRE[-8:]
                    voiced = voiced + 1 if is_speech else 0
                    if voiced >= 3:  # ~90 ms of consecutive speech
                        speaking, buf, silent = True, list(PRE), 0
                        self.on_state("hearing")
                else:
                    buf.append(chunk)
                    silent = 0 if is_speech else silent + 1
                    if silent > 28:  # ~850 ms of silence ends the utterance (people pause mid-sentence)
                        pcm = np.concatenate(buf)
                        buf, speaking, silent, voiced, PRE = [], False, 0, 0, []
                        if len(pcm) > SAMPLE_RATE * 0.4:
                            self.on_state("thinking")
                            self._queue.put(pcm)  # one worker transcribes clips strictly in order
                        else:
                            self.on_state("listening")
                    elif len(buf) > SAMPLE_RATE * 15 / FRAME:  # hard cap 15 s
                        silent = 999

    def _worker(self):
        while True:
            pcm = self._queue.get()
            if pcm is None:
                return
            try:
                text = self.transcribe(pcm)
                if text:
                    self.on_utterance(text)
            except Exception as e:
                print(f"voice worker error: {e}")
            self.on_state("listening")
