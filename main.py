import os
import queue
import threading
import webbrowser

import customtkinter as ctk
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import agents
import wallet as wl
from gaze import GazeController
from server import server as llama
from voice import Voice

APP_NAME = os.getenv("APP_NAME", "Monad Voice Agents")

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

AGENT_COLORS = {
    "User": "#9ca3af", "Orchestrator": "#a78bfa", "System": "#60a5fa", "Vision": "#34d399",
    "Writer": "#fbbf24", "Wallet": "#f472b6", "Guardian": "#f87171",
}
STATE_STYLE = {"idle": ("Idle", "#6b7280"), "listening": ("Listening…", "#22c55e"),
               "hearing": ("Hearing you…", "#facc15"), "thinking": ("Thinking…", "#a78bfa")}


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1180x720")
        self.q = queue.Queue()
        self.voice = Voice(self.on_utterance, on_state=lambda s: self.q.put(("state", s)))
        self.listening = False
        self.gaze = GazeController(on_event=lambda m: self.q.put(("event", "System", "tool", m)))
        agents.on_mode_change = lambda m: self.q.put(("mode", m))

        agents.bus.on_event = lambda a, k, t: self.q.put(("event", a, k, t))
        agents.bus.speak = self._speak

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_main()
        self.after(100, self._pump)
        self.refresh_wallet()

    # ── layout ────────────────────────────────────────────────────────────
    def _build_sidebar(self):
        sb = ctk.CTkFrame(self, width=300, corner_radius=0)
        sb.grid(row=0, column=0, sticky="nsew")
        sb.grid_propagate(False)
        ctk.CTkLabel(sb, text=APP_NAME, font=ctk.CTkFont(size=20, weight="bold"), wraplength=260).pack(padx=20, pady=(24, 4))
        ctk.CTkLabel(sb, text="Hands-free computing + Monad", text_color="gray").pack()

        self.mic_btn = ctk.CTkButton(sb, text="🎙  START LISTENING", height=46, fg_color="#16a34a",
                                     hover_color="#15803d", command=self.toggle_listen)
        self.mic_btn.pack(padx=20, pady=(22, 8), fill="x")
        self.state_lbl = ctk.CTkLabel(sb, text="Idle", text_color="#6b7280", font=ctk.CTkFont(size=14, weight="bold"))
        self.state_lbl.pack()

        self.mode_sw = ctk.CTkSwitch(sb, text="Assistant mode", command=self.on_mode_switch)
        self.mode_sw.select()
        self.mode_sw.pack(pady=(14, 4))
        self.gaze_btn = ctk.CTkButton(sb, text="👁  Calibrate eye tracking", fg_color="#374151", command=self.run_calibration)
        self.gaze_btn.pack(padx=20, pady=4, fill="x")
        self.gaze_sw = ctk.CTkSwitch(sb, text="Gaze cursor + blink click", command=self.on_gaze_switch, state="disabled")
        self.gaze_sw.pack(pady=4)
        backend = "Gemma 4 (local)" if agents.BACKEND == "local" else f"{agents.MODEL} (cloud)"
        ctk.CTkLabel(sb, text=f"LLM: {backend}", text_color="gray", font=ctk.CTkFont(size=11)).pack(pady=(4, 0))

        card = ctk.CTkFrame(sb, corner_radius=12)
        card.pack(padx=16, pady=14, fill="x")
        ctk.CTkLabel(card, text="MONAD TESTNET WALLET", font=ctk.CTkFont(size=11, weight="bold"), text_color="gray").pack(pady=(12, 2))
        self.bal_lbl = ctk.CTkLabel(card, text="— MON", font=ctk.CTkFont(size=28, weight="bold"))
        self.bal_lbl.pack()
        try:
            a = wl.address()
            short = a[:8] + "…" + a[-6:]
        except Exception:
            a, short = "", "no wallet"
        self.addr_lbl = ctk.CTkLabel(card, text=short, text_color="gray", font=ctk.CTkFont(family="Menlo", size=12))
        self.addr_lbl.pack(pady=(0, 6))
        ctk.CTkButton(card, text="Refresh", width=80, height=26, fg_color="#374151", command=self.refresh_wallet).pack(pady=(0, 12))

        ctk.CTkLabel(sb, text="GUARDIAN", font=ctk.CTkFont(size=11, weight="bold"), text_color="gray").pack(pady=(4, 4))
        row = ctk.CTkFrame(sb, fg_color="transparent")
        row.pack(padx=16, fill="x")
        self.ok_btn = ctk.CTkButton(row, text="✓ Confirm", fg_color="#16a34a", hover_color="#15803d", state="disabled",
                                    command=lambda: agents.gate.resolve(True, "button"))
        self.ok_btn.pack(side="left", expand=True, fill="x", padx=(0, 4))
        self.no_btn = ctk.CTkButton(row, text="✕ Cancel", fg_color="#dc2626", hover_color="#b91c1c", state="disabled",
                                    command=lambda: agents.gate.resolve(False, "button"))
        self.no_btn.pack(side="left", expand=True, fill="x", padx=(4, 0))
        self.guard_lbl = ctk.CTkLabel(sb, text="Nothing awaiting approval", text_color="gray", wraplength=260)
        self.guard_lbl.pack(pady=8, padx=16)

    def _build_main(self):
        main = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew", padx=16, pady=16)
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(main, text="Agent activity", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, sticky="w", pady=(0, 6))
        self.feed = ctk.CTkTextbox(main, font=("Menlo", 13), wrap="word")
        self.feed.grid(row=1, column=0, sticky="nsew")
        for name, col in AGENT_COLORS.items():
            self.feed.tag_config(name, foreground=col)
        self.feed.tag_config("link", foreground="#38bdf8", underline=True)
        self.feed.tag_bind("link", "<Button-1>", self._click_link)
        self.feed.configure(state="disabled")

        bar = ctk.CTkFrame(main, fg_color="transparent")
        bar.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        bar.grid_columnconfigure(0, weight=1)
        self.entry = ctk.CTkEntry(bar, placeholder_text="Or type a command…  (e.g. send 0.1 MON to Alice)", height=40)
        self.entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.entry.bind("<Return>", lambda e: self.submit_text())
        ctk.CTkButton(bar, text="Send", width=80, height=40, command=self.submit_text).grid(row=0, column=1)

    # ── actions ───────────────────────────────────────────────────────────
    def refresh_wallet(self):
        def work():
            try:
                self.q.put(("balance", f"{wl.balance():.4f} MON"))
            except Exception:
                self.q.put(("balance", "offline"))
        threading.Thread(target=work, daemon=True).start()

    def on_mode_switch(self):
        agents.set_mode("assistant" if self.mode_sw.get() else "transcribe")

    def run_calibration(self):
        self.q.put(("event", "System", "tool", "Eye calibration starting: follow the dots, then the 9 points."))
        self.iconify()
        self.after(400, self._do_calibration)  # OpenCV windows must run on the main thread

    def _do_calibration(self):
        try:
            self.gaze.calibrate()
            self.gaze_sw.configure(state="normal")
            self.gaze_sw.select()
            self.gaze.start()
        except Exception as e:
            self._append("System", "error", f"Calibration failed: {e}")
        finally:
            self.deiconify()

    def on_gaze_switch(self):
        self.gaze.start() if self.gaze_sw.get() else self.gaze.stop()

    def toggle_listen(self):
        if not self.listening:
            self.mic_btn.configure(text="Loading…", state="disabled")
            threading.Thread(target=self._start_voice, daemon=True).start()
        else:
            self.voice.stop()
            self.listening = False
            self.mic_btn.configure(text="🎙  START LISTENING", fg_color="#16a34a")
            self._set_state("idle")

    def _start_voice(self):
        try:
            if agents.BACKEND == "local":
                self.q.put(("event", "System", "tool", "Starting local Gemma 4 server (first load takes a bit)…"))
                llama.start()
            self.voice.start()
            self.listening = True
            self.q.put(("mic_on",))
        except Exception as e:
            self.q.put(("event", "Orchestrator", "error", f"Voice failed: {e}"))
            self.q.put(("mic_off",))

    def on_utterance(self, text: str):
        """Called from the voice thread. Confirmations short-circuit the orchestrator."""
        if agents.gate.handle_utterance(text):
            self.q.put(("event", "User", "say", text))
            return
        if agents.gate.active:  # a confirmation is pending; ignore unrelated chatter
            return
        threading.Thread(target=self._run_agents, args=(text,), daemon=True).start()

    def submit_text(self):
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, "end")
        self.on_utterance(text)

    def _run_agents(self, text):
        agents.handle(text)
        self.refresh_wallet()

    def _speak(self, text):
        self.voice.speak(text)

    # ── UI pump (main thread only) ────────────────────────────────────────
    def _set_state(self, s):
        text, col = STATE_STYLE.get(s, STATE_STYLE["idle"])
        self.state_lbl.configure(text=text, text_color=col)

    def _append(self, agent, kind, text):
        self.feed.configure(state="normal")
        self.feed.insert("end", f"{agent:<13}", agent)
        tag = "link" if text.startswith("http") else None
        label = {"say": "🎤 ", "route": "", "tool": "🛠 ", "reply": "💬 ", "ask": "⚠️  ", "approved": "✅ ",
                 "denied": "🛑 ", "tx": "🔗 ", "review": "🔍 ", "send": "⛓ ", "error": "❗ ", "timeout": "⏱ "}.get(kind, "")
        self.feed.insert("end", f"{label}{text}\n", tag)
        self.feed.configure(state="disabled")
        self.feed.see("end")

    def _click_link(self, event):
        idx = self.feed.index(f"@{event.x},{event.y}")
        line = self.feed.get(f"{idx} linestart", f"{idx} lineend")
        for w in line.split():
            if w.startswith("http"):
                webbrowser.open(w.rstrip(".,"))
                break

    def _pump(self):
        try:
            while True:
                m = self.q.get_nowait()
                kind = m[0]
                if kind == "event":
                    _, a, k, t = m
                    self._append(a, k, t)
                    if a == "Guardian" and k == "ask":
                        self.ok_btn.configure(state="normal")
                        self.no_btn.configure(state="normal")
                        self.guard_lbl.configure(text=t, text_color="#fbbf24")
                    elif a == "Guardian" and k in ("approved", "denied", "timeout"):
                        self.ok_btn.configure(state="disabled")
                        self.no_btn.configure(state="disabled")
                        self.guard_lbl.configure(text="Nothing awaiting approval", text_color="gray")
                elif kind == "mode":
                    self.mode_sw.select() if m[1] == "assistant" else self.mode_sw.deselect()
                    self.mode_sw.configure(text="Assistant mode" if m[1] == "assistant" else "Transcribe mode")
                elif kind == "state":
                    self._set_state(m[1])
                elif kind == "balance":
                    self.bal_lbl.configure(text=m[1])
                elif kind == "mic_on":
                    self.mic_btn.configure(text="■  STOP LISTENING", fg_color="#dc2626", state="normal")
                elif kind == "mic_off":
                    self.mic_btn.configure(text="🎙  START LISTENING", fg_color="#16a34a", state="normal")
        except queue.Empty:
            pass
        self.after(100, self._pump)


if __name__ == "__main__":
    app = App()
    if app.gaze.load_saved():
        app.gaze_sw.configure(state="normal")
        app.gaze_sw.deselect()
        app._append("System", "tool", "Saved eye calibration loaded. Toggle 'Gaze cursor' to use it.")

    def _quit():
        try:
            llama.stop()
        finally:
            app.destroy()
    app.protocol("WM_DELETE_WINDOW", _quit)
    app.mainloop()
