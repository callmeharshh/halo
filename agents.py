"""Multi-agent core: Orchestrator -> {System, Vision, Writer, Wallet} agents, with a Guardian gate on money."""
import json
import re
import threading
import time
from decimal import Decimal

from dotenv import load_dotenv
from openai import OpenAI

import safety
import system_tools as st
import wallet as wl

load_dotenv()
import os

BACKEND = os.getenv("LLM_BACKEND", "openai")  # "openai" (cloud) or "local" (Gemma 4 via llama.cpp)
if BACKEND == "local":
    MODEL = "Gemma4"
    client = OpenAI(base_url="http://127.0.0.1:8080/v1", api_key="local", timeout=180.0, max_retries=1)
else:
    MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1")
    client = OpenAI(timeout=20.0, max_retries=3)  # fail fast, retry transient network errors


def clean(text: str) -> str:
    """Strip Gemma thought channels / stray tags so only speakable text remains."""
    if not text:
        return ""
    text = re.sub(r"<\|channel\|?>thought.*?<channel\|>", "", text, flags=re.S)
    text = re.sub(r"<\|?[a-z_]+\|?>", "", text)
    return re.sub(r"\s+", " ", text).strip()


# ── plumbing ─────────────────────────────────────────────────────────────────
class Bus:
    """Event sink + speech sink, swapped in by the UI. Everything the agents do flows through here."""

    def __init__(self):
        self.on_event = lambda agent, kind, text: print(f"[{agent}] {kind}: {text}")
        self.speak = lambda text: print(f"SAY: {text}")
        self.is_speaking = lambda: False  # UI swaps in the real TTS state


bus = Bus()


def fn(name, desc, props=None, required=None):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props or {}, "required": required or []}}}


class Agent:
    """One LLM + its own system prompt + its own tools. Runs a tool loop and returns final text."""

    def __init__(self, name, system, tools, handlers, max_turns=5):
        self.name, self.system, self.tools, self.handlers, self.max_turns = name, system, tools, handlers, max_turns

    def run(self, messages: list, extra_context: str = "") -> str:
        lang = " Reply in English unless the user's request is actually in Hindi or Hinglish; then reply in Devanagari Hindi."
        msgs = [{"role": "system", "content": self.system + lang + extra_context}] + messages
        for _ in range(self.max_turns):
            r = client.chat.completions.create(
                model=MODEL, messages=msgs, tools=self.tools or None, temperature=0.2)
            m = r.choices[0].message
            if not m.tool_calls:
                return clean(m.content)
            msgs.append(m)
            for tc in m.tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                bus.on_event(self.name, "tool", f"{tc.function.name}({_short(args)})")
                h = self.handlers.get(tc.function.name)
                try:
                    out = h(**args) if h else f"Unknown tool {tc.function.name}"
                except Exception as e:  # tool errors go back to the model, never crash the loop
                    out = f"Error: {e}"
                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": str(out)})
        return "I couldn't finish that."


def _short(args):
    s = json.dumps(args, ensure_ascii=False)
    return s if len(s) < 80 else s[:77] + "..."


# ── Guardian: gate for risky actions ─────────────────────────────────────────
class ConfirmationGate:
    """Blocks a worker thread until the user confirms/cancels by voice, button, or blink."""

    def __init__(self):
        self._event = threading.Event()
        self._decision = None
        self.last_source = "voice"  # how the most recent approval happened, recorded on-chain
        self.pending = None  # description of what is awaiting approval
        self.armed = False   # only listen for "confirm" AFTER our read-back has finished speaking
        self.last_send = 0.0

    @property
    def active(self):
        return self.pending is not None

    def ask(self, description: str, spoken: str, timeout: float = 25.0) -> bool:
        self._event.clear()
        self._decision = None
        self.armed = False
        self.pending = description
        bus.on_event("Guardian", "ask", description)
        bus.speak(spoken + " Say confirm, or cancel.")
        t0 = time.time()
        time.sleep(0.3)
        while bus.is_speaking() and time.time() - t0 < 15:  # don't arm until the read-back is over
            time.sleep(0.1)
        time.sleep(0.4)  # let the room echo die so we never "hear" our own prompt
        self.armed = True
        answered = self._event.wait(timeout)
        if not answered:
            bus.on_event("Guardian", "timeout", "No response, cancelled.")
        ok = answered and self._decision is True
        self.armed = False
        self.pending = None
        return ok

    def resolve(self, decision: bool, source: str = "voice"):
        if self.pending is None:
            return
        self._decision = decision
        self.last_source = source
        bus.on_event("Guardian", "approved" if decision else "denied", f"via {source}")
        self._event.set()

    def handle_utterance(self, text: str) -> bool:
        """Return True if the utterance was consumed as a confirmation answer."""
        if not self.active:
            return False
        if not self.armed:
            return True  # speech that finished while we were still talking: ignore, never treat as consent
        verdict = safety.classify_reply(text)
        if verdict == "cancel":
            self.resolve(False, "voice")
            return True
        if verdict == "confirm":
            self.resolve(True, "voice")
            return True
        return False  # unrelated speech: keep waiting


gate = ConfirmationGate()


def guardian_review(prep: dict) -> tuple[str, str]:
    """Deterministic risk review of a prepared transfer. Returns (level, note)."""
    bal = wl.vault_balance()
    known = bool(prep.get("contact"))
    pct = (prep["amount"] / bal * 100) if bal else Decimal(100)
    flags = []
    if not known:
        flags.append("this address is not in your contacts")
    if pct > 50:
        flags.append(f"it is {pct:.0f} percent of your balance")
    level = "HIGH" if len(flags) >= 2 else ("MEDIUM" if flags else "LOW")
    bus.on_event("Guardian", "review", f"risk {level}" + (f": {'; '.join(flags)}" if flags else ""))
    return level, ("Warning: " + " and ".join(flags) + ". ") if flags else ""


# ── Wallet agent tools ───────────────────────────────────────────────────────
def t_balance():
    return f"Vault (spendable by the agent): {wl.vault_balance():.4f} MON. Wallet: {wl.balance():.4f} MON."


def t_policy():
    p = wl.policy()
    return (f"On-chain safety policy: max {p['max_per_tx'].normalize():f} MON per transfer, "
            f"{p['daily_limit'].normalize():f} MON per day, "
            f"{'only saved contacts' if p['trusted_only'] else 'any recipient'}.")


def t_my_address():
    return wl.address()


def t_list_contacts():
    return json.dumps(wl.load_contacts())


def t_add_contact(name, address):
    return wl.add_contact(name, address)


def t_tx_status(tx_hash):
    return wl.tx_status(tx_hash)


current_request = ""  # what the user literally said this turn (set by handle()); used to cross-check money amounts
SEND_COOLDOWN = 6.0


def t_send_mon(recipient, amount):
    """The ONLY path to moving money. Cross-checks the request, reads it back, waits for human approval,
    then goes through the on-chain GuardVault. Every doubt resolves to NOT sending."""
    if time.time() - gate.last_send < SEND_COOLDOWN:
        return "A payment just went out. Please wait a few seconds before sending another."
    if gate.active:
        return "Another payment is already waiting for approval."
    # 1) the amount must be something the user actually said, not something the model inferred
    if not safety.amount_matches_speech(amount, current_request):
        bus.on_event("Guardian", "review", f"amount {amount} not found in what was said: '{current_request}'")
        return ("Not sent. I am not certain about the amount. Ask the user to repeat the full request clearly, "
                "for example: 'send zero point one MON to Alice'.")
    try:
        prep = wl.prepare_transfer(recipient, amount)
    except wl.WalletError as e:
        return f"Rejected: {e}"
    level, note = guardian_review(prep)
    short = prep["to"][:6] + "…" + prep["to"][-4:]
    shown = f"{note}Send {prep['amount'].normalize():f} MON to {prep['label']} ({short})."
    spoken = f"{note}Send {safety.say_amount(prep['amount'])} MON to {prep['label']}."
    if not gate.ask(shown, spoken):
        return "Transfer cancelled by the user. Nothing was sent."
    method = gate.last_source
    bus.on_event("Wallet", "send", f"GuardVault.guardedSend({prep['amount']} MON → {prep['label']}, approvedBy={method})")
    try:
        h = wl.send_mon(prep, method)
    except Exception as e:
        bus.on_event("Guardian", "denied", str(e))
        return f"Transfer failed: {e}"
    gate.last_send = time.time()
    url = wl.explorer_url(h)
    bus.on_event("Wallet", "tx", url)
    return f"Sent. Transaction confirmed on Monad. Hash {h}. Explorer: {url}"


WALLET = Agent(
    "Wallet",
    "You are the Wallet agent for a hands-free accessibility assistant on the Monad testnet (currency: MON). "
    "Use your tools for balances, contacts, and transfers. To send money ALWAYS call send_mon; it asks the user "
    "to confirm by voice itself, so never ask for confirmation yourself and never claim a transfer happened unless "
    "send_mon says Sent. NEVER guess: if the amount or the recipient is missing or unclear, ask the user instead of "
    "calling send_mon. Never change an amount the user said. If send_mon says Not sent or Rejected, relay that "
    "plainly and ask the user to repeat. Reply in one or two short spoken-style sentences. Do not read out long "
    "hashes or addresses.",
    [
        fn("get_balance", "Get the user's MON balances (vault and wallet)."),
        fn("get_policy", "Explain the on-chain safety limits that protect the user's funds."),
        fn("get_my_address", "Get the user's wallet address."),
        fn("list_contacts", "List saved contacts."),
        fn("add_contact", "Save a contact.", {"name": {"type": "string"}, "address": {"type": "string"}}, ["name", "address"]),
        fn("send_mon", "Send MON to a contact name or 0x address. Triggers the voice-confirmation gate.",
           {"recipient": {"type": "string"}, "amount": {"type": "number"}}, ["recipient", "amount"]),
        fn("tx_status", "Check the status of a transaction hash.", {"tx_hash": {"type": "string"}}, ["tx_hash"]),
    ],
    {"get_balance": t_balance, "get_policy": t_policy, "get_my_address": t_my_address, "list_contacts": t_list_contacts,
     "add_contact": t_add_contact, "send_mon": t_send_mon, "tx_status": t_tx_status},
)

# ── System agent ─────────────────────────────────────────────────────────────
SYSTEM = Agent(
    "System",
    "You are the System agent controlling a Mac for a user who cannot use a keyboard or mouse. "
    "Use tools to open apps, files, websites, press keys, scroll, change volume, set timers, read the clipboard. "
    "Be decisive: act, then confirm in one short spoken sentence.",
    [
        fn("open_app", "Open a Mac application by name.", {"app_name": {"type": "string"}}, ["app_name"]),
        fn("open_path", "Open a file or folder by path or fuzzy name.", {"query": {"type": "string"}}, ["query"]),
        fn("open_url", "Open a website URL or run a Google search.",
           {"url_or_query": {"type": "string"}, "search": {"type": "boolean"}}, ["url_or_query", "search"]),
        fn("press_key", "Press a key or combo like 'cmd+c', 'cmd+tab', 'enter', 'cmd+w'.", {"key_combo": {"type": "string"}}, ["key_combo"]),
        fn("scroll", "Scroll up or down.", {"direction": {"type": "string", "enum": ["up", "down"]}, "amount": {"type": "integer"}}, ["direction"]),
        fn("set_volume", "Set system volume 0-100.", {"level": {"type": "integer"}}, ["level"]),
        fn("set_timer", "Set a countdown timer in seconds.", {"seconds": {"type": "integer"}, "label": {"type": "string"}}, ["seconds"]),
        fn("get_time_date", "Current date and time."),
        fn("get_system_info", "CPU, RAM and battery."),
        fn("get_clipboard", "Read the clipboard."),
        fn("set_clipboard", "Copy text to the clipboard.", {"text": {"type": "string"}}, ["text"]),
        fn("click_at", "Click at screen coordinates.", {"x": {"type": "integer"}, "y": {"type": "integer"}}, ["x", "y"]),
    ],
    {
        "open_app": st.open_app, "open_path": st.open_path, "open_url": st.open_url,
        "press_key": st.press_key, "scroll": st.scroll, "set_volume": st.set_volume,
        "set_timer": lambda seconds, label="Timer": st.set_timer(seconds, label, lambda m: bus.speak(m)),
        "get_time_date": st.get_time_date, "get_system_info": st.get_system_info,
        "get_clipboard": st.get_clipboard, "set_clipboard": st.set_clipboard, "click_at": st.click_at,
    },
)


# ── Vision agent ─────────────────────────────────────────────────────────────
def t_look(question="Describe what is on the screen."):
    b64 = st.screenshot_b64()
    r = client.chat.completions.create(model=MODEL, messages=[{"role": "user", "content": [
        {"type": "text", "text": question + " Answer concisely for someone who cannot see the screen."},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}])
    return r.choices[0].message.content


VISION = Agent(
    "Vision",
    "You are the Vision agent. You can look at the user's screen via look_at_screen and describe or answer "
    "questions about it, read text aloud, or summarize it. Reply in one to three short spoken sentences.",
    [fn("look_at_screen", "Capture the screen and answer a question about it.", {"question": {"type": "string"}})],
    {"look_at_screen": t_look},
)

# ── Writer agent ─────────────────────────────────────────────────────────────
WRITER = Agent(
    "Writer",
    "You are the Writer agent. The user dictates text; you clean it up (grammar, punctuation, spoken filler, "
    "code syntax if it is code) and then call type_text with ONLY the final text. After typing, say 'Done.'",
    [fn("type_text", "Type text into the active app.", {"text": {"type": "string"}}, ["text"])],
    {"type_text": st.type_text},
)

SPECIALISTS = {"system": SYSTEM, "vision": VISION, "writer": WRITER, "wallet": WALLET}


# ── Orchestrator ─────────────────────────────────────────────────────────────
ORCH_SYSTEM = (
    "You are the Orchestrator of a voice-driven accessibility assistant for people with physical disabilities. "
    "The user speaks; you route the request to ONE specialist agent via delegate(), or answer simple chit-chat yourself. "
    "Agents: system (apps, files, web, keys, volume, timers, clipboard, time), vision (look at or read the screen), "
    "writer (dictate/type text into the active app), wallet (Monad MON balance, contacts, sending money). "
    "Pass the user's request faithfully in 'task' (keep any amounts and names exactly as spoken). Speech is "
    "transcribed, so expect small mishearings (e.g. 'Alis' = Alice). The user may speak English, Hindi or Hinglish: "
    "understand all of them. Reply in ENGLISH whenever the user's words are English. ONLY if the user's words are actually "
    "Hindi or Hinglish (e.g. 'bhej do', 'kya hai', Devanagari) reply in Hindi written in Devanagari so it is spoken correctly. Be warm, simple and patient: many users are elderly "
    "or not tech-savvy. Keep your own replies to one short sentence."
)
ORCH_TOOLS = [fn("delegate", "Hand the task to a specialist agent.",
                 {"agent": {"type": "string", "enum": list(SPECIALISTS)}, "task": {"type": "string"}},
                 ["agent", "task"])]

history: list[dict] = []
_lock = threading.Lock()

# ── transcribe (dictation) mode ──────────────────────────────────────────────
mode = "assistant"
_chunks: list[str] = []
_timer = None
on_mode_change = lambda m: None


def set_mode(m: str):
    global mode
    mode = m
    on_mode_change(m)
    bus.on_event("Orchestrator", "route", f"mode → {m}")


def _flush_dictation():
    global _chunks, _timer
    raw, _chunks, _timer = " ".join(_chunks), [], None
    if not raw.strip():
        return
    try:
        r = client.chat.completions.create(model=MODEL, messages=[{"role": "user", "content":
            "Clean this dictated text: fix grammar and punctuation, remove filler words. If it is code, fix the "
            "syntax for the language. If it is mathematics, convert it to LaTeX. Return ONLY the final text, "
            "no quotes, no commentary:\n\n" + raw}], temperature=0.1)
        text = clean(r.choices[0].message.content).strip("\"'")
        if text:
            bus.on_event("Writer", "tool", f"type_text({_short({'text': text})})")
            st.type_text(text)
    except Exception as e:
        bus.on_event("Writer", "error", str(e))


def _dictate(text: str):
    global _timer
    _chunks.append(text)
    if _timer:
        _timer.cancel()
    _timer = threading.Timer(2.5, _flush_dictation)
    _timer.start()


def handle(user_text: str) -> str:
    """Entry point from the voice/text UI. Returns the spoken reply."""
    low = user_text.lower()
    if "transcribe mode" in low or "dictation mode" in low:
        bus.on_event("User", "say", user_text)
        set_mode("transcribe")
        bus.speak("Transcribe mode on.")
        return "Transcribe mode on."
    if "assistant mode" in low:
        bus.on_event("User", "say", user_text)
        set_mode("assistant")
        bus.speak("Assistant mode on.")
        return "Assistant mode on."
    if mode == "transcribe":
        bus.on_event("User", "say", user_text)
        _dictate(user_text)
        return ""
    global current_request
    with _lock:  # one request at a time
        current_request = user_text
        bus.on_event("User", "say", user_text)
        history.append({"role": "user", "content": user_text})
        msgs = [{"role": "system", "content": ORCH_SYSTEM}] + history[-12:]
        reply = ""
        try:
            r = client.chat.completions.create(model=MODEL, messages=msgs, tools=ORCH_TOOLS, temperature=0.1)
            m = r.choices[0].message
            if m.tool_calls:
                tc = m.tool_calls[0]
                args = json.loads(tc.function.arguments or "{}")
                name = args.get("agent", "system")
                task = args.get("task", user_text)
                bus.on_event("Orchestrator", "route", f"→ {name} agent: {task}")
                reply = SPECIALISTS[name].run([{"role": "user", "content": task}])
            else:
                reply = clean(m.content)
        except Exception as e:
            bus.on_event("Orchestrator", "error", str(e))
            reply = "Sorry, something went wrong."
        history.append({"role": "assistant", "content": reply})
        if len(history) > 30:
            del history[:-20]
        bus.on_event("Orchestrator", "reply", reply)
        bus.speak(reply)
        return reply
