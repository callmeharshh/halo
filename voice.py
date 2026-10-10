"""Mac voice I/O: mic capture + WebRTC VAD + Parakeet STT, and TTS via `say`."""
import subprocess
import threading
import time

import io
import os
import wave

import numpy as np
import onnx_asr
import sounddevice as sd
import webrtcvad

SAMPLE_RATE = 16000
FRAME = 480  # 30 ms @ 16 kHz, a size webrtcvad accepts


class Voice:
    def __init__(self, on_utterance, on_state=None, voice_name="Samantha", rate=185):
        self.on_utterance = on_utterance  # callback(text)
        self.on_state = on_state or (lambda s: None)
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
            self._oa = OpenAI()
        self._stop = threading.Event()
        self._thread = None
        self._say_proc = None
        self._speaking_until = 0.0

    # ── TTS ──────────────────────────────────────────────────────────────
    def speak(self, text: str):
        if not text or not text.strip():
            return
        self.stop_speaking()
        self._speaking_until = time.time() + 600  # blocks mic until say exits
        self._say_proc = subprocess.Popen(["say", "-v", self.voice_name, "-r", str(self.rate), text])
        threading.Thread(target=self._wait_say, args=(self._say_proc,), daemon=True).start()

    def _wait_say(self, proc):
        proc.wait()
        if proc is self._say_proc:
            self._speaking_until = time.time() + 0.4  # tail so we don't hear our own echo

    def stop_speaking(self):
        if self._say_proc and self._say_proc.poll() is None:
            self._say_proc.terminate()

    def is_speaking(self) -> bool:
        return time.time() < self._speaking_until

    # ── STT ──────────────────────────────────────────────────────────────
    def transcribe(self, pcm: np.ndarray) -> str:
        if self.backend == "openai":
            try:
                bio = io.BytesIO()
                with wave.open(bio, "wb") as w:
                    w.setnchannels(1); w.setsampwidth(2); w.setframerate(SAMPLE_RATE)
                    w.writeframes(pcm.astype(np.int16).tobytes())
                bio.name = "speech.wav"; bio.seek(0)
                r = self._oa.audio.transcriptions.create(
                    model="gpt-4o-mini-transcribe", file=bio, language="en",
                    prompt="Voice commands for a computer assistant: open apps, send MON to Alice, confirm, cancel.")
                return r.text.strip()
            except Exception as e:
                print(f"STT error: {e}")
                return ""
        audio = pcm.astype(np.float32) / 32768.0
        try:
            return str(self.stt.recognize(audio)).strip()
        except Exception as e:
            print(f"STT error: {e}")
            return ""

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
        PRE = []  # small pre-roll so we don't clip the first syllable
        self.on_state("listening")
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16", blocksize=FRAME) as stream:
            while not self._stop.is_set():
                data, _ = stream.read(FRAME)
                chunk = data[:, 0].copy()
                if self.is_speaking():  # ignore mic while the assistant talks
                    buf, speaking, silent, voiced, PRE = [], False, 0, 0, []
                    continue
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
                    if silent > 20:  # ~600 ms of silence ends the utterance
                        pcm = np.concatenate(buf)
                        buf, speaking, silent, voiced, PRE = [], False, 0, 0, []
                        if len(pcm) > SAMPLE_RATE * 0.4:
                            self.on_state("thinking")
                            threading.Thread(target=self._handle, args=(pcm,), daemon=True).start()
                        else:
                            self.on_state("listening")
                    elif len(buf) > SAMPLE_RATE * 15 / FRAME:  # hard cap 15 s
                        silent = 999

    def _handle(self, pcm):
        text = self.transcribe(pcm)
        if text:
            self.on_utterance(text)
        self.on_state("listening")
