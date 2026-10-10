"""Launches the local llama.cpp server (Gemma 4 E4B + vision) on macOS / Metal."""
import glob
import os
import subprocess
import time

import requests

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MODEL = os.path.join(BASE_DIR, "model", "google_gemma-4-E4B-it-Q4_K_M.gguf")
MMPROJ = os.path.join(BASE_DIR, "model", "mmproj-google_gemma-4-E4B-it-f16.gguf")
TEMPLATE = os.path.join(BASE_DIR, "model", "chat_template.jinja")
PORT = 8080
URL = f"http://127.0.0.1:{PORT}"


def _binary() -> str:
    hits = glob.glob(os.path.join(BASE_DIR, "llamacpp", "*", "llama-server"))
    if not hits:
        raise FileNotFoundError("llama-server not found under llamacpp/")
    return hits[0]


def is_up() -> bool:
    try:
        return requests.get(f"{URL}/health", timeout=1).status_code == 200
    except requests.RequestException:
        return False


class LlamaServer:
    def __init__(self):
        self.process = None

    def start(self, timeout=180):
        if is_up():  # already running (e.g. started by hand)
            return
        for p in (MODEL, MMPROJ, TEMPLATE):
            if not os.path.exists(p):
                raise FileNotFoundError(f"Missing model file: {p}")
        exe = _binary()
        cmd = [
            exe, "-m", MODEL, "--mmproj", MMPROJ, "--chat-template-file", TEMPLATE, "--jinja",
            "--port", str(PORT), "--host", "127.0.0.1",
            "--parallel", "1", "-c", "12288", "-ngl", "99", "--flash-attn", "on",
            "--cache-type-k", "q8_0", "--cache-type-v", "q8_0",
            "--temp", "0.1", "--top-k", "40",
            "--image-min-tokens", "256", "--image-max-tokens", "1120",
            "--no-warmup", "--reasoning-format", "deepseek", "--reasoning-budget", "0",
        ]
        self.process = subprocess.Popen(
            cmd, cwd=os.path.dirname(exe),
            stdout=subprocess.DEVNULL, stderr=open(os.path.join(BASE_DIR, "llama-server.log"), "w"),
        )
        for _ in range(timeout):
            if self.process.poll() is not None:
                raise RuntimeError("llama-server exited; see llama-server.log")
            if is_up():
                return
            time.sleep(1)
        raise RuntimeError("llama-server did not become ready in time")

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=10)


server = LlamaServer()
