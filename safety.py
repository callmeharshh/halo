"""Payment-safety helpers. Pure functions (no network, no UI) so they can be unit-tested.

Design rule: speech-to-text WILL mishear. Never trust one transcription for money. We cross-check what the
LLM wants to send against what the user literally said, read everything back, and default to NOT sending.
"""
import re
from decimal import Decimal, InvalidOperation

from rapidfuzz import fuzz, process

# ── numbers ──────────────────────────────────────────────────────────────────
_EN = {"zero": 0, "oh": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
       "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
       "fifty": 50, "hundred": 100, "half": 0.5, "quarter": 0.25}
_HI = {"शून्य": 0, "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पांच": 5, "पाँच": 5, "छह": 6, "छः": 6, "सात": 7,
       "आठ": 8, "नौ": 9, "दस": 10, "बीस": 20, "पचास": 50, "सौ": 100, "आधा": 0.5,
       "ek": 1, "do": 2, "teen": 3, "char": 4, "paanch": 5, "panch": 5, "chhe": 6, "saat": 7, "aath": 8,
       "nau": 9, "das": 10, "bees": 20, "pachaas": 50, "sau": 100, "aadha": 0.5}
# "do"/"दो" is both the number two AND the verb "give" ("bhej do" = "send it"): only count it as a number
# when a unit word follows. Otherwise we fail safe and ask the user to repeat the amount.
_AMBIGUOUS = {"do", "दो"}
_UNITS = {"mon", "मोन", "मॉन", "token", "tokens", "rupee", "rupees", "rupaye", "रुपये", "रुपए", "rs"}
_DEV_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
_POINT = ("point", "dot", "दशमलव", "पॉइंट", "पॉइन्ट", "dashmalav")


def numbers_in(text: str) -> list[Decimal]:
    """Every number the user said, as Decimals ("zero point one" -> 0.1, "दो" -> 2, "0.5" -> 0.5)."""
    t = text.lower().translate(_DEV_DIGITS)
    # split on whitespace/punctuation, NOT \w: Python's \w drops Devanagari vowel marks and chops Hindi words apart
    toks = re.findall(r"\d+(?:\.\d+)?|[^\s\d.,!?;:'\"()]+|\.", t)
    vals: list[Decimal] = []
    i = 0
    while i < len(toks):
        tok = toks[i]
        if re.fullmatch(r"\d+(?:\.\d+)?", tok):
            vals.append(Decimal(tok))
        elif tok in _AMBIGUOUS and not (i + 1 < len(toks) and toks[i + 1] in _UNITS):
            pass  # verb "do/दो", not the number
        elif tok in _EN or tok in _HI:
            whole = Decimal(str(_EN.get(tok, _HI.get(tok))))
            # "zero point one" / "0 point 5" / "एक दशमलव पांच": integer-word, point, then digit words
            if i + 2 < len(toks) and toks[i + 1] in _POINT:
                frac = ""
                j = i + 2
                while j < len(toks) and (toks[j] in _EN or toks[j] in _HI or re.fullmatch(r"\d", toks[j])):
                    d = toks[j] if re.fullmatch(r"\d", toks[j]) else str(_EN.get(toks[j], _HI.get(toks[j])))
                    if "." in d or len(d) > 1:
                        break
                    frac += d
                    j += 1
                if frac:
                    vals.append(Decimal(f"{whole}.{frac}"))
                    i = j
                    continue
            vals.append(whole)
        elif tok in _POINT and vals and i + 1 < len(toks) and re.fullmatch(r"\d+", toks[i + 1]):
            # "0 point 5" where 0 was already captured as a digit token
            vals[-1] = Decimal(f"{vals[-1]}.{toks[i + 1]}")
            i += 1
        i += 1
    return vals


def amount_matches_speech(amount, spoken: str) -> bool:
    """True only if the amount the model wants to send actually appears in what the user said."""
    try:
        want = Decimal(str(amount))
    except InvalidOperation:
        return False
    return any(want == v for v in numbers_in(spoken))


def say_amount(amount: Decimal) -> str:
    """Read an amount back digit-by-digit style so a mishearing is obvious: 0.1 -> 'zero point one'."""
    names = "zero one two three four five six seven eight nine".split()
    s = format(Decimal(str(amount)).normalize(), "f")
    return " ".join("point" if c == "." else names[int(c)] for c in s) if len(s) <= 8 else s


# ── confirm / cancel ─────────────────────────────────────────────────────────
_CANCEL_EN = ("cancel", "no", "nope", "stop", "abort", "reject", "don't", "dont", "do not", "never mind", "wait")
_CANCEL_HI = ("नहीं", "नही", "रुको", "रुकिए", "मत", "रहने दो", "nahi", "nahin", "mat", "ruko", "rehne do", "ruk")
_CONFIRM_EN = ("confirm", "confirmed", "yes", "yeah", "yep", "approve", "approved", "go ahead", "do it",
               "send it", "proceed", "okay send", "ok send")
_CONFIRM_HI = ("हाँ", "हां", "हा", "कन्फर्म", "पक्का", "कर दो", "भेज दो", "ठीक है", "haan", "han", "ha",
               "pakka", "kar do", "bhej do", "theek hai", "confirm")


def _has(text: str, words) -> bool:
    for w in words:
        if re.search(r"[ऀ-ॿ]", w):  # Devanagari: \b is unreliable with combining marks
            if w in text:
                return True
        elif re.search(rf"(?<![a-z']){re.escape(w)}(?![a-z'])", text):
            return True
    return False


def classify_reply(text: str) -> str | None:
    """'confirm', 'cancel', or None (unrelated speech, ignore it). Cancel always beats confirm."""
    t = text.lower().strip()
    if not t:
        return None
    if _has(t, _CANCEL_EN) or _has(t, _CANCEL_HI):
        return "cancel"
    if len(t.split()) <= 6 and (_has(t, _CONFIRM_EN) or _has(t, _CONFIRM_HI)):
        return "confirm"  # long rambling sentences are not a confirmation
    return None


# ── contacts ────────────────────────────────────────────────────────────────
def _skeleton(name: str) -> str:
    """Rough phonetic key: consonant skeleton. alice/alis/elise/alicia -> 'ls'; alex -> 'lks'."""
    t = re.sub(r"[^a-z]", "", name.lower())
    t = re.sub(r"c(?=[eiy])", "s", t)
    t = t.replace("ck", "k").replace("ph", "f").replace("x", "ks").replace("z", "s").replace("c", "k")
    t = re.sub(r"[aeiouyhw]", "", t)
    return re.sub(r"(.)\1+", r"\1", t)


def match_contact(heard: str, names: list[str], min_ratio: int = 80) -> tuple[str | None, str]:
    """Match a (possibly misheard) name against saved contacts, but only when it is UNAMBIGUOUS.

    'Alis' -> 'alice' is accepted. A weak match, or a name that fits two contacts, is refused so the
    assistant asks the user instead of guessing. Exact (normalised) matches always win.
    """
    h = re.sub(r"[^a-z0-9\u0900-\u097F ]", "", heard.lower()).strip()
    if not h or not names:
        return None, "no name heard"
    if h in names:
        return h, ""
    hs = _skeleton(h)
    hits = [n for n in names if (hs and _skeleton(n) == hs) or fuzz.ratio(h, n) >= min_ratio]
    if len(hits) == 1:
        return hits[0], ""
    if not hits:
        return None, f"no saved contact sounds like '{heard}'"
    return None, f"'{heard}' could be {' or '.join(hits)}"
