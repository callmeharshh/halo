"""Halo Journeys: the Inclusive Travel Agent brain.

  outline(request)  -> itinerary + the key places to validate        (LLM, structured JSON)
  research(place)   -> accessibility facts WITH real web citations   (LLM + web search)
  plan(...)         -> PlanResult, streaming progress events

Honesty rules baked into the prompts: only state what sources support, say "unknown" otherwise, never invent.
The citation links come from the search tool's own annotations, not from the model's text.
"""
import concurrent.futures as cf
import datetime
import json
import os
import re
import threading

from dotenv import load_dotenv
from openai import OpenAI

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.getenv("HALO_ENV_PATH") or os.path.join(ROOT, ".env"))

MODEL = os.getenv("TRAVEL_MODEL", "gpt-4.1")
client = OpenAI(timeout=75.0, max_retries=2)
CACHE_PATH = os.path.join(ROOT, "travel", "cache.json")
_cache_lock = threading.Lock()

FEATURES = ["step_free", "ramp", "elevator", "accessible_restroom", "accessible_room",
            "tactile_braille", "hearing_loop_sign", "quiet_space", "assistance_service", "accessible_parking"]
NEED_TEXT = {
    "wheelchair": "uses a wheelchair or has limited mobility (step-free routes, ramps, lifts, accessible restrooms/rooms matter most)",
    "blind": "is blind or has low vision (tactile paving, braille/audio signage, guide or assistance services, predictable layouts matter most)",
    "deaf": "is deaf or hard of hearing (visual announcements, hearing loops, sign-language or text-based help matter most)",
    "cognitive": "has a cognitive or sensory-processing disability (simple clear routes, quiet low-sensory spaces, patient assistance matter most)",
    "elderly": "is elderly (short walking distances, seating, lifts, assistance, avoiding stairs matter most)",
}


def _load_cache() -> dict:
    try:
        return json.load(open(CACHE_PATH))
    except Exception:
        return {}


def _save_cache(c: dict):
    try:
        json.dump(c, open(CACHE_PATH, "w"), indent=1, ensure_ascii=False)
    except Exception:
        pass


def _json_from(text: str) -> dict:
    """Pull the first JSON object out of a model reply."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError("no JSON in reply")
    return json.loads(m.group(0))


def _lang_rule(lang: str) -> str:
    return ("Write all free-text fields (title, summary, notes, tips, summaries, draft bodies) in Hindi using Devanagari script; keep place names in English."
            if lang == "hi" else "Write in clear, simple English.")


def _needs_text(needs: list[str]) -> str:
    parts = [NEED_TEXT[n] for n in needs if n in NEED_TEXT]
    return "; ".join(parts) or "has no specific need stated: still prioritise step-free, seated and assisted options"


# ── 1. outline ───────────────────────────────────────────────────────────────
def outline(request: str, needs: list[str], lang: str = "en") -> dict:
    okey = "outline|" + request.strip().lower() + "|" + ",".join(sorted(needs)) + "|" + lang + "|v2"
    with _cache_lock:
        hit = _load_cache().get(okey)
    if hit:
        return hit  # a repeated request (e.g. a rehearsed demo) is instant
    data = _outline_llm(request, needs, lang)
    with _cache_lock:
        c = _load_cache(); c[okey] = data; _save_cache(c)
    return data


def _outline_llm(request: str, needs: list[str], lang: str = "en") -> dict:
    sys = (
        "You are an inclusive travel planner. Plan an accessibility-first trip. The traveller " + _needs_text(needs) + ". "
        "Use real, well-known places in the real destination. Prefer step-free, well-connected, assisted options, and keep days realistic "
        "(few stops, rest breaks, no rushed transfers). "
        + _lang_rule(lang) +
        " Reply with ONLY a JSON object: "
        '{"title":str,"summary":str (2-3 sentences),"traveler":{"needs":[str],"notes":str},'
        '"days":[{"day":int,"title":str,"items":[{"time":"HH:MM","kind":"transport|stay|place|food","name":str,"city":str,"note":str,"place":str|null}]}],'
        '"places":[{"name":str,"city":str,"kind":"airport|station|hotel|attraction|restaurant"}],"tips":[str]}. '
        "RULES: 'places' = the 4 to 6 most important venues to validate (always include the arrival airport or station and the hotel); "
        "every item with kind place/stay or an airport/station must set 'place' to EXACTLY the matching places[].name (else null); "
        "no more than 4 items per day; do not invent prices; budget advice only in the notes. "
        "IMPORTANT: at this stage nothing has been verified, so NEVER claim a place is accessible, wheelchair-friendly or barrier-free in the title, summary, notes or tips. "
        "Say places were chosen because they are LIKELY to suit the traveller and that the accessibility details below must be checked."
    )
    r = client.chat.completions.create(model=MODEL, temperature=0.3, response_format={"type": "json_object"},
                                       messages=[{"role": "system", "content": sys}, {"role": "user", "content": request}])
    data = json.loads(r.choices[0].message.content)
    data.setdefault("traveler", {"needs": needs, "notes": ""})["needs"] = needs
    data["places"] = [p for p in data.get("places", []) if p.get("name")][:6]
    return data


# ── 2. research one place (web search with citations) ───────────────────────
def _search(query_prompt: str):
    """Forced web search. Returns (text, sources). Citation links come from the tool's own annotations."""
    r = client.responses.create(model=MODEL, tools=[{"type": "web_search_preview"}], tool_choice={"type": "web_search_preview"}, input=query_prompt)
    sources, seen = [], set()
    for o in r.output:
        if getattr(o, "type", "") == "message":
            for ct in o.content:
                for a in getattr(ct, "annotations", None) or []:
                    if getattr(a, "type", "") == "url_citation":
                        url = re.sub(r"[?&]utm_source=openai.*$", "", a.url)
                        if "google.com/maps" in url or "maps.google" in url:  # a map search is not evidence
                            continue
                        if url not in seen:
                            seen.add(url); sources.append({"title": (a.title or url)[:90], "url": url})
    return r.output_text, sources


def research(place: dict, needs: list[str], lang: str = "en") -> dict:
    key = (place["name"].strip().lower() + "|" + (place.get("city") or "").strip().lower() + "|" + ",".join(sorted(needs)) + "|" + lang + "|v2")
    with _cache_lock:
        cached = _load_cache().get(key)
    if cached:
        cached["access"]["sources"] = [x for x in cached["access"].get("sources", []) if "google.com/maps" not in x["url"]]
        return cached
    out = {"name": place["name"], "city": place.get("city", ""), "kind": place.get("kind", "place"),
           "access": {"features": {f: "unknown" for f in FEATURES}, "summary": "No reliable accessibility information was found online. Please confirm directly with the venue.",
                      "confidence": "low", "sources": []},
           "draft": {"channel": "email", "subject": f"Accessibility questions for my visit: {place['name']}",
                     "body": f"Hello,\n\nI am planning to visit {place['name']}. Could you please confirm the accessibility arrangements (step-free entrance, accessible restrooms, assistance on arrival) for my needs?\n\nThank you."}}
    try:
        # step 1: forced web search, plain facts with citations
        text, sources = _search(
            f"Search the web for the accessibility of {place['name']} in {place.get('city', '')} ({place.get('kind', 'place')}). "
            f"The traveller {_needs_text(needs)}. Write 5 to 8 short factual bullet points about step-free access, ramps, lifts/elevators, "
            "accessible restrooms, accessible rooms or seating, tactile/braille signage, hearing loops or sign language, quiet space, assistance services, "
            "accessible parking. Only include what sources actually state; write 'not stated' for the rest. Cite sources.")
        # step 2: structure the findings (no tools), without adding facts
        feats_keys = ",".join(f'"{f}":"yes|no|unknown"' for f in FEATURES)
        r = client.chat.completions.create(model=MODEL, temperature=0, response_format={"type": "json_object"}, messages=[
            {"role": "system", "content": (
                "Convert research notes into JSON. Use ONLY facts in the notes; use \"unknown\" for anything not stated. Reply with ONLY: "
                '{"features":{' + feats_keys + '},"summary":str (2 sentences on what matters for this traveller),"confidence":"high|medium|low",'
                '"draft":{"subject":str,"body":str}}. '
                "confidence: high only if the notes show two or more independent sources agree; low if sparse or conflicting. "
                "draft = a short polite message to the venue asking 3 to 5 SPECIFIC questions to confirm what the traveller needs (e.g. is the entrance step-free, "
                "is there an accessible room, can staff meet us on arrival). The traveller " + _needs_text(needs) + ". " + _lang_rule(lang))},
            {"role": "user", "content": f"Place: {place['name']}, {place.get('city', '')}\n\nResearch notes:\n{text}"}])
        data = json.loads(r.choices[0].message.content)
        feats = data.get("features", {})
        conf = data.get("confidence") if data.get("confidence") in ("high", "medium", "low") else "low"
        domains = {re.sub(r"^https?://(www\.)?", "", x["url"]).split("/")[0] for x in sources}
        if conf == "high" and len(domains) < 2:
            conf = "medium"
        if not sources:
            conf = "low"
        out["access"] = {"features": {f: (feats.get(f) if feats.get(f) in ("yes", "no", "unknown") else "unknown") for f in FEATURES},
                         "summary": data.get("summary") or out["access"]["summary"], "confidence": conf, "sources": sources[:4]}
        d = data.get("draft") or {}
        if d.get("body"):
            out["draft"] = {"channel": "email", "subject": d.get("subject") or out["draft"]["subject"], "body": d["body"]}
    except Exception as e:
        out["access"]["summary"] = "Could not complete online research for this place (" + str(e)[:60] + "). Please confirm directly with the venue."
    with _cache_lock:
        c = _load_cache(); c[key] = out; _save_cache(c)
    return out


# ── 3. the full plan, streaming progress ─────────────────────────────────────
def plan(request: str, needs: list[str], lang: str, emit) -> dict:
    needs = [n for n in needs if n in NEED_TEXT]
    emit({"event": "stage", "text": "Understanding your trip and planning the days…"})
    base = outline(request, needs, lang)
    places = base.get("places", [])
    emit({"event": "stage", "text": f"Found {len(places)} key places to check for accessibility."})
    results: dict[str, dict] = {}
    done = [0]
    lock = threading.Lock()

    def work(p):
        res = research(p, needs, lang)
        with lock:
            done[0] += 1
            emit({"event": "stage", "text": f"Checked {p['name']} ({done[0]}/{len(places)}): {res['access']['confidence']} confidence, {len(res['access']['sources'])} source(s)."})
        return p["name"], res

    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        for p in places:
            emit({"event": "stage", "text": f"Researching {p['name']} online…"})
        for name, res in ex.map(work, places):
            results[name] = res
    base["places"] = [results.get(p["name"], p) for p in places]
    base["generated_at"] = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    base.setdefault("tips", [])
    return base
