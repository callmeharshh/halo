"""macOS system tools used by the System / Writer / Vision agents."""
import base64
import datetime
import os
import subprocess
import tempfile
import threading
import time

import psutil
import pyautogui
import pyperclip
from rapidfuzz import fuzz, process

pyautogui.FAILSAFE = False

_KEYMAP = {"win": "command", "cmd": "command", "windows": "command", "control": "ctrl",
           "option": "option", "alt": "option", "return": "enter", "escape": "esc"}


def open_app(app_name: str) -> str:
    r = subprocess.run(["open", "-a", app_name], capture_output=True, text=True)
    if r.returncode == 0:
        return f"Opened {app_name}."
    # fuzzy fall-back against installed apps
    apps = []
    for d in ("/Applications", "/System/Applications", os.path.expanduser("~/Applications")):
        if os.path.isdir(d):
            apps += [f[:-4] for f in os.listdir(d) if f.endswith(".app")]
    m = process.extractOne(app_name, apps, scorer=fuzz.WRatio)
    if m and m[1] > 70:
        subprocess.run(["open", "-a", m[0]])
        return f"Opened {m[0]}."
    return f"Could not find an app called {app_name}."


def open_path(query: str) -> str:
    """Open a file/folder by exact path or fuzzy name under Desktop/Documents/Downloads."""
    p = os.path.expanduser(query)
    if os.path.exists(p):
        subprocess.run(["open", p])
        return f"Opened {p}."
    home = os.path.expanduser("~")
    names = {}
    for d in ("Desktop", "Documents", "Downloads"):
        root = os.path.join(home, d)
        for dp, dns, fns in os.walk(root):
            dns[:] = [x for x in dns if not x.startswith(".")]
            for n in fns + dns:
                names[n] = os.path.join(dp, n)
            if len(names) > 8000:
                break
    m = process.extractOne(query, names.keys(), scorer=fuzz.WRatio)
    if m and m[1] > 65:
        subprocess.run(["open", names[m[0]]])
        return f"Opened {m[0]}."
    return f"No confident match for '{query}'."


def open_url(url_or_query: str, search: bool = False) -> str:
    import urllib.parse
    import webbrowser
    if search:
        url = "https://www.google.com/search?q=" + urllib.parse.quote_plus(url_or_query)
    else:
        url = url_or_query if url_or_query.startswith("http") else "https://" + url_or_query
    webbrowser.open(url)
    return f"Opened {url}."


def press_key(key_combo: str) -> str:
    keys = [_KEYMAP.get(k.strip(), k.strip()) for k in key_combo.lower().split("+")]
    pyautogui.hotkey(*keys) if len(keys) > 1 else pyautogui.press(keys[0])
    return f"Pressed {key_combo}."


def type_text(text: str) -> str:
    """Paste via clipboard (handles unicode, fast, reliable on Mac)."""
    time.sleep(0.5)
    old = pyperclip.paste()
    pyperclip.copy(text)
    pyautogui.hotkey("command", "v")
    time.sleep(0.2)
    pyperclip.copy(old)
    return "Typed it."


def scroll(direction: str, amount: int = 5) -> str:
    pyautogui.scroll(amount * 10 if direction == "up" else -amount * 10)
    return f"Scrolled {direction}."


def click_at(x: int, y: int, button: str = "left") -> str:
    pyautogui.click(x, y, button=button)
    return f"Clicked at {x},{y}."


def set_volume(level: int) -> str:
    level = max(0, min(100, int(level)))
    subprocess.run(["osascript", "-e", f"set volume output volume {level}"])
    return f"Volume set to {level} percent."


def get_clipboard() -> str:
    return pyperclip.paste() or "(clipboard is empty)"


def set_clipboard(text: str) -> str:
    pyperclip.copy(text)
    return "Copied to clipboard."


def get_time_date() -> str:
    return datetime.datetime.now().strftime("It is %A, %B %d, %I:%M %p.")


def get_system_info() -> str:
    ram = psutil.virtual_memory()
    bat = psutil.sensors_battery()
    b = f" Battery {bat.percent:.0f} percent." if bat else ""
    return f"CPU {psutil.cpu_percent(interval=0.3):.0f} percent, RAM {ram.percent:.0f} percent used.{b}"


def set_timer(seconds: int, label: str = "Timer", callback=None) -> str:
    def done():
        time.sleep(int(seconds))
        if callback:
            callback(f"{label} is done.")
    threading.Thread(target=done, daemon=True).start()
    return f"{label} set for {seconds} seconds."


def screenshot_b64(max_w: int = 1280) -> str:
    """Capture the screen to a base64 JPEG using the macOS screencapture tool."""
    from PIL import Image
    import io
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "s.png")
        subprocess.run(["screencapture", "-x", path], check=True)
        img = Image.open(path).convert("RGB")
        if img.width > max_w:
            img = img.resize((max_w, int(img.height * max_w / img.width)))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=75)
    return base64.b64encode(buf.getvalue()).decode()
