"""Halo Journeys Concierge: a root agent that hands off to 14 specialist roles (our own implementation).

REAL: itinerary planning, web research WITH citations, on-chain accessibility reads (AccessRegistry), drafting of messages,
      checklists, risk review, barrier alternatives, cost estimates (clearly estimates).
SIMULATED (labelled `simulated: true`): bookings, payment, web check-in, sending emails, scheduled reminders.
Inspired by the structure of Google's open-source 'inclusive-travel-agent' sample (Apache-2.0); no code is copied.
"""
import hashlib
import json
import os
import re
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import agent as A  # noqa: E402

ROOT = A.ROOT
client, MODEL = A.client, A.MODEL
SESSIONS: dict[str, dict] = {}

ROLES = {
    "inspiration_agent": "Suggests accessible destinations and activities.",
    "planning_agent": "Plans the trip day by day, compares cost against accessibility.",
    "booking_agent": "Prepares bookings with accessibility accommodations (simulated).",
    "pre_trip_agent": "Travel advisories, weather and preparation requirements (web search).",
    "in_trip_agent": "Real-time support while travelling.",
    "post_trip_agent": "Collects accessibility feedback and offers to record it on Monad.",
    "accessibility_research_agent": "Researches a place's accessibility on the web with sources and checks Monad.",
    "mobility_preparation_agent": "Mobility aids, medical documents, packing.",
    "transit_support_agent": "Airport and station assistance, priority services.",
    "barrier_navigation_agent": "Immediate alternatives when a barrier appears.",
    "notification_agent": "Reminders and confirmations schedule (simulated).",
    "accessibility_communication_agent": "Drafts proactive accessibility messages to venues and carriers.",
    "web_checkin_agent": "Web check-in with accessible seating (simulated).",
    "smart_guardrails_agent": "Risk and compliance review of the plan, with on-chain checks.",
}


# ── helpers ──────────────────────────────────────────────────────────────────
def jcall(system: str, user: str, temp: float = 0.3) -> dict:
    r = client.chat.completions.create(model=MODEL, temperature=temp, response_format={"type": "json_object"},
                                       messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
    return json.loads(r.choices[0].message.content)


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())).strip()


def derive_needs(profile: dict, text: str) -> list[str]:
    needs = [n for n in (profile.get("needs") or []) if n in A.NEED_TEXT]
    low = text.lower()
    for key, words in {"wheelchair": ("wheelchair", "mobility", "walker", "crutch"), "blind": ("blind", "low vision", "guide dog", "white cane"),
                       "deaf": ("deaf", "hard of hearing", "hearing aid"), "cognitive": ("autis", "cognitive", "dyslex", "adhd", "sensory"),
                       "elderly": ("elderly", "senior", "my mother", "my father", "grandm", "grandf")}.items():
        if key not in needs and any(w in low for w in words):
            needs.append(key)
    return needs


def ptext(profile: dict) -> str:
    bits = []
    for k, label in (("name", "Name"), ("home", "Home city"), ("aids", "Mobility aids/equipment"), ("assist", "Assistance preferences"),
                     ("budget", "Usual budget (INR)"), ("language", "Language"), ("emergency", "Emergency contact")):
        if profile.get(k):
            bits.append(f"{label}: {profile[k]}")
    if profile.get("needs"):
        bits.append("Access needs: " + ", ".join(profile["needs"]))
    return "; ".join(bits) or "No profile provided."


def plan_ctx(S: dict) -> str:
    p = S.get("plan")
    if not p:
        return "No plan exists yet."
    lines = [f"Plan: {p.get('title')}. {p.get('summary', '')}"]
    for d in p.get("days", []):
        lines.append(f"Day {d['day']}: " + "; ".join(f"{i.get('time', '')} {i.get('name')}" for i in d.get("items", [])))
    for pl in p.get("places", []):
        lines.append(f"Place: {pl['name']} ({pl.get('city')}, {pl.get('kind')}), web confidence {pl['access']['confidence']}, sources {len(pl['access']['sources'])}")
    return "\n".join(lines)


def chain_summary(name: str, city: str):
    """Real on-chain read of the AccessRegistry for a place (None if unreachable)."""
    try:
        import wallet as wl
        d = json.load(open(os.path.join(ROOT, "contracts", "deployment.AccessRegistry.json")))
        c = wl.w3.eth.contract(address=d["address"], abi=d["abi"])
        pid = c.functions.placeId(norm(name), norm(city)).call()
        s = wl.with_retry(lambda: c.functions.summary(pid).call())
        return {"attesters": int(s[0]), "confirmed": int(s[1]), "counts": [int(x) for x in s[2]]}
    except Exception:
        return None


def art(emit, kind, title, data, agent):
    emit({"event": "artifact", "kind": kind, "title": title, "data": data, "agent": agent})


# ── specialist agents: fn(task, S, emit) -> short summary string for the root ─
def inspiration_agent(task, S, emit):
    d = jcall("You are an accessible-destination inspiration agent. Suggest 4 real destinations that suit the traveller. " + A._lang_rule(S["lang"]) +
              ' Reply ONLY JSON: {"places":[{"name":str,"country":str,"why":str (1 sentence),"access_note":str (what to check first; never claim it is accessible)}],"intro":str}.',
              f"Traveller profile: {ptext(S['profile'])}\nRequest: {task}")
    art(emit, "inspiration", "Destination ideas", {"places": d.get("places", [])[:5]}, "inspiration_agent")
    return "Suggested destinations: " + ", ".join(p["name"] for p in d.get("places", [])) + ". " + (d.get("intro") or "")


def planning_agent(task, S, emit):
    needs = derive_needs(S["profile"], task)
    st = {"found": 0}

    def stage(ev):
        t = ev.get("text", "")
        if t.startswith("Found"):
            emit({"event": "agent", "name": "accessibility_research_agent", "status": "start", "note": t})
        elif t.startswith("Checked") and re.search(r"\((\d+)/(\d+)\)", t):
            m = re.search(r"\((\d+)/(\d+)\)", t)
            if m.group(1) == m.group(2):
                emit({"event": "agent", "name": "accessibility_research_agent", "status": "done", "note": "All places researched with sources"})
    req = task + ("\nTraveller profile: " + ptext(S["profile"]))
    plan = A.plan(req, needs, S["lang"], stage)
    S["plan"], S["needs"] = plan, needs
    art(emit, "plan", plan["title"], plan, "planning_agent")
    # budget & route decisions
    try:
        b = jcall("You estimate trip costs in Indian rupees. Use realistic ESTIMATES, not exact quotes. " + A._lang_rule(S["lang"]) +
                  ' Reply ONLY JSON: {"currency":"INR","lines":[{"label":str,"amount":number,"note":str}],"disability_costs":[{"label":str,"amount":number}],"summary":str}. '
                  "Include transport, stay, food, local accessible transport; disability_costs = extra expenses such as assistance services or accessible taxis (use 0 if free, e.g. airport wheelchair assistance); "
                  "summary = 2 sentences comparing cost against accessibility and where paying more is worth it.",
                  f"Plan:\n{plan_ctx(S)}\nBudget stated: {S['profile'].get('budget') or 'see request'}\nRequest: {task}")
        b["total"] = round(sum(float(x.get("amount", 0)) for x in b.get("lines", [])) + sum(float(x.get("amount", 0)) for x in b.get("disability_costs", [])))
        art(emit, "budget", "Budget and route decisions (estimates)", b, "planning_agent")
    except Exception:
        pass
    conf = ", ".join(f"{p['name']} [{p['access']['confidence']}]" for p in plan["places"])
    return f"Created the plan '{plan['title']}' with {len(plan['places'])} researched places: {conf}. A cost estimate was added."


def accessibility_research_agent(task, S, emit):
    m = jcall('Extract the venue from the request. Reply ONLY JSON: {"name":str,"city":str,"kind":"airport|station|hotel|attraction|restaurant"}.', task)
    needs = derive_needs(S["profile"], task) or S.get("needs", [])
    res = A.research({"name": m.get("name") or task[:60], "city": m.get("city", ""), "kind": m.get("kind", "place")}, needs, S["lang"])
    mini = {"title": "Accessibility check: " + res["name"], "summary": res["access"]["summary"], "traveler": {"needs": needs, "notes": ""}, "days": [], "places": [res], "tips": [], "generated_at": ""}
    art(emit, "plan", mini["title"], mini, "accessibility_research_agent")
    return f"Researched {res['name']}: confidence {res['access']['confidence']}, {len(res['access']['sources'])} sources. {res['access']['summary']}"


def booking_agent(task, S, emit):
    d = jcall("You prepare SIMULATED bookings (no real booking system is connected). " + A._lang_rule(S["lang"]) +
              ' Reply ONLY JSON: {"items":[{"label":str,"detail":str (include the accessibility accommodation requested, e.g. wheelchair assistance code WCHR, accessible room, aisle seat),"price":str (an estimate)}]}.',
              f"Plan:\n{plan_ctx(S)}\nProfile: {ptext(S['profile'])}\nTask: {task}")
    art(emit, "booking", "Booking prepared (simulated)", {"items": d.get("items", []), "simulated": True}, "booking_agent")
    return "Prepared simulated bookings with accessibility accommodations: " + "; ".join(i["label"] for i in d.get("items", []))


def pre_trip_agent(task, S, emit):
    dest = (S.get("plan") or {}).get("title") or task
    text, sources = A._search(f"Current travel advisories, weather outlook and health or document requirements for: {dest}. Short bullet points, with sources.")
    srcs = "\n".join(f"- {s['title']}: {s['url']}" for s in sources[:4])
    emit({"event": "message", "agent": "pre_trip_agent", "text": (text[:900] + ("\n\nSources:\n" + srcs if srcs else ""))})
    return "Pre-trip information gathered: " + text[:400]


def mobility_preparation_agent(task, S, emit):
    d = jcall("You prepare a practical checklist for a traveller with a disability. " + A._lang_rule(S["lang"]) +
              ' Reply ONLY JSON: {"groups":[{"name":str,"items":[str]}]} with groups: Mobility aids and equipment; Medical documents and medicines; Accessibility confirmations to carry; Packing; Day-before. 3-6 items each, specific to the profile and plan.',
              f"Profile: {ptext(S['profile'])}\nPlan:\n{plan_ctx(S)}\nTask: {task}")
    art(emit, "checklist", "Preparation checklist", {"groups": d.get("groups", [])}, "mobility_preparation_agent")
    return "Created a preparation checklist covering equipment, documents, packing and the day before."


def transit_support_agent(task, S, emit):
    d = jcall("You plan assisted transit. " + A._lang_rule(S["lang"]) +
              ' Reply ONLY JSON: {"legs":[{"from":str,"to":str,"mode":str,"assistance":str (what to request and from whom),"tip":str}]}. Do not invent phone numbers or guarantees.',
              f"Plan:\n{plan_ctx(S)}\nProfile: {ptext(S['profile'])}\nTask: {task}")
    art(emit, "transit", "Transit and assistance", {"legs": d.get("legs", [])}, "transit_support_agent")
    return f"Prepared {len(d.get('legs', []))} transit legs with assistance requests."


def barrier_navigation_agent(task, S, emit):
    d = jcall("A traveller with a disability hit a barrier on the trip. Give immediate, practical alternatives. " + A._lang_rule(S["lang"]) +
              ' Reply ONLY JSON: {"issue":str,"options":[{"title":str,"detail":str,"cost_hint":str}]} with 3 options, safest first. Never invent specific venues unless they are in the plan.',
              f"Profile: {ptext(S['profile'])}\nPlan:\n{plan_ctx(S)}\nSituation: {task}")
    art(emit, "barrier", "Alternatives right now", d, "barrier_navigation_agent")
    return "Offered alternatives: " + "; ".join(o["title"] for o in d.get("options", []))


def notification_agent(task, S, emit):
    items = [
        {"when": "14 days before", "what": "Send accessibility requests to hotels and carriers", "agent": "accessibility_communication_agent", "status": "scheduled"},
        {"when": "7 days before", "what": "Confirm assistance bookings in writing and check documents", "agent": "notification_agent", "status": "scheduled"},
        {"when": "48 hours before", "what": "Reminder: medicines, mobility aids, charged devices", "agent": "notification_agent", "status": "scheduled"},
        {"when": "24 hours before", "what": "Web check-in with accessible seating", "agent": "web_checkin_agent", "status": "simulated"},
        {"when": "Day of travel", "what": "Assistance meeting points and emergency contact on standby", "agent": "transit_support_agent", "status": "scheduled"},
        {"when": "1 day after return", "what": "Short accessibility feedback survey (and record it on Monad)", "agent": "post_trip_agent", "status": "scheduled"},
    ]
    if S["profile"].get("emergency"):
        items.insert(2, {"when": "On departure", "what": "Share itinerary with emergency contact: " + str(S["profile"]["emergency"]), "agent": "notification_agent", "status": "simulated"})
    art(emit, "schedule", "Reminders and confirmations", {"items": items, "simulated": True}, "notification_agent")
    return "Set up a reminder and confirmation schedule (simulated; nothing is actually sent)."


def accessibility_communication_agent(task, S, emit):
    out = []
    for p in (S.get("plan") or {}).get("places", [])[:4]:
        dr = p.get("draft") or {}
        if dr.get("body"):
            out.append({"to": p["name"], "channel": "email", "subject": dr.get("subject", ""), "body": dr["body"], "send_after": "7 to 14 days before arrival"})
    try:
        d = jcall("You write short, polite, specific messages. " + A._lang_rule(S["lang"]) +
                  ' Reply ONLY JSON: {"items":[{"to":str,"channel":"email|whatsapp","subject":str,"body":str}]} with exactly 1 message to the airline or railway requesting assistance (for example wheelchair assistance) and 1 to the hotel requesting an accessible room. Ask for written confirmation. Use only facts in the plan.',
                  f"Profile: {ptext(S['profile'])}\nPlan:\n{plan_ctx(S)}\nTask: {task}")
        for it in d.get("items", []):
            it["send_after"] = "7 to 14 days before arrival"; out.append(it)
    except Exception:
        pass
    art(emit, "drafts", "Messages to confirm accessibility (drafts)", {"items": out}, "accessibility_communication_agent")
    return f"Drafted {len(out)} messages to venues and carriers (drafts only; you send them)."


def web_checkin_agent(task, S, emit):
    d = jcall("You prepare a SIMULATED web check-in. " + A._lang_rule(S["lang"]) +
              ' Reply ONLY JSON: {"flight":str,"opens":str,"seat":str (accessible seat strategy for this profile),"note":str}. Do not invent flight numbers; say "your outbound flight".',
              f"Profile: {ptext(S['profile'])}\nPlan:\n{plan_ctx(S)}")
    d["simulated"] = True
    art(emit, "checkin", "Web check-in plan (simulated)", d, "web_checkin_agent")
    return "Prepared a simulated web check-in plan with an accessible seating strategy."


def smart_guardrails_agent(task, S, emit):
    p = S.get("plan")
    findings = []
    if p:
        for pl in p.get("places", []):
            cs = chain_summary(pl["name"], pl.get("city", ""))
            acc = pl["access"]
            if cs and cs["attesters"] == 0:
                findings.append({"level": "caution", "text": f"{pl['name']}: no traveller has attested this place on Monad yet (web confidence: {acc['confidence']}).",
                                 "fix": "Send the drafted confirmation message and ask the venue to confirm in writing."})
            elif cs and cs["attesters"] > 0:
                findings.append({"level": "info", "text": f"{pl['name']}: {cs['attesters']} traveller(s) attested this on Monad, {cs['confirmed']} said the venue confirmed it.", "fix": ""})
            if acc["confidence"] == "low" or not acc["sources"]:
                findings.append({"level": "risk", "text": f"{pl['name']}: little reliable information online.", "fix": "Treat as unverified. Have a backup option."})
    try:
        d = jcall("You are a travel safety reviewer for travellers with disabilities. Review the plan for realistic risks: tight transfers, long distances, rest breaks, "
                  "heat, missing assistance, cash/payment friction. " + A._lang_rule(S["lang"]) +
                  ' Reply ONLY JSON: {"findings":[{"level":"info|caution|risk","text":str,"fix":str}]} with 3 to 5 findings.',
                  f"Profile: {ptext(S['profile'])}\nPlan:\n{plan_ctx(S)}\nTask: {task}")
        findings += d.get("findings", [])
    except Exception:
        pass
    lv = [f["level"] for f in findings]
    overall = "risk" if "risk" in lv else "caution" if "caution" in lv else "ok"
    art(emit, "guardrails", "Safety and compliance review", {"overall": overall, "findings": findings[:10]}, "smart_guardrails_agent")
    return f"Review result: {overall}. " + "; ".join(f["text"] for f in findings[:3])


def in_trip_agent(task, S, emit):
    r = client.chat.completions.create(model=MODEL, temperature=0.3, messages=[
        {"role": "system", "content": "You are an in-trip assistant for a traveller with a disability. Be calm, practical and brief (max 120 words). " + A._lang_rule(S["lang"]) + " Never invent facts about venues."},
        {"role": "user", "content": f"Profile: {ptext(S['profile'])}\nPlan:\n{plan_ctx(S)}\nSituation: {task}"}])
    txt = r.choices[0].message.content.strip()
    emit({"event": "message", "agent": "in_trip_agent", "text": txt})
    return "In-trip guidance given: " + txt[:300]


def post_trip_agent(task, S, emit):
    d = jcall("You collect accessibility feedback after a trip. " + A._lang_rule(S["lang"]) +
              ' Reply ONLY JSON: {"questions":[str],"attest_suggestion":{"place":str,"city":str,"features":[int]}|null}. Feature indexes: 0 step-free,1 ramp,2 lift,3 accessible restroom,4 accessible room/seating,5 tactile/braille,6 hearing loop/sign,7 quiet space,8 assistance,9 accessible parking. '
              "Only set attest_suggestion if the traveller's message clearly states what they found at a specific place in the plan; otherwise null and ask 3 short questions.",
              f"Plan:\n{plan_ctx(S)}\nTraveller says: {task}")
    art(emit, "feedback", "Your feedback helps the next traveller", {"questions": d.get("questions", []), "attest_suggestion": d.get("attest_suggestion")}, "post_trip_agent")
    return "Collected feedback" + (" and prepared an on-chain attestation to confirm." if d.get("attest_suggestion") else "; asked follow-up questions.")


FUNCS = {n: globals()[n] for n in ROLES}

TRANSFER = {"type": "function", "function": {
    "name": "transfer_to_agent", "description": "Hand the task to a specialist agent.",
    "parameters": {"type": "object", "properties": {"agent_name": {"type": "string", "enum": list(ROLES)}, "task": {"type": "string"}}, "required": ["agent_name", "task"]}}}

ROOT_SYSTEM = (
    "You are the Concierge of Halo Journeys, a warm, calm travel concierge for travellers with disabilities. You orchestrate specialist agents by calling transfer_to_agent.\n"
    "Agents:\n" + "\n".join(f"- {k}: {v}" for k, v in ROLES.items()) + "\n"
    "Routing: a trip request -> planning_agent (it already researches places with sources). After a NEW plan also call smart_guardrails_agent. "
    "'what to prepare/pack' -> mobility_preparation_agent. 'reminders/notify/confirm' -> notification_agent and accessibility_communication_agent. "
    "'book' -> booking_agent. 'check in' -> web_checkin_agent. 'airport/station assistance' -> transit_support_agent. 'destination ideas' -> inspiration_agent. "
    "'is X accessible' -> accessibility_research_agent. A broken lift / barrier -> barrier_navigation_agent. Travel advisories/weather/visa -> pre_trip_agent. "
    "Feedback after a trip -> post_trip_agent. Live problems while travelling -> in_trip_agent. 'review risks/safety' -> smart_guardrails_agent. Chit-chat: answer yourself.\n"
    "Call at most 3 agents per turn. After the agents finish, write a SHORT final message (max 90 words) summarising what was done and suggesting ONE next step. "
    "HONESTY: never claim a place is accessible unless a source says so, and never describe the trip or its places as 'accessible', 'wheelchair-friendly' or 'barrier-free'; say 'planned around your needs' and that details must be confirmed; bookings, payments, web check-in, reminders and sending messages are SIMULATED in this demo and you must say so plainly when you use them; "
    "messages to venues are drafts the traveller sends."
)


# ── the turn ─────────────────────────────────────────────────────────────────
def _turn_key(msg, S):
    base = msg.strip().lower() + "|" + (S.get("plan") or {}).get("title", "") + "|" + ",".join(sorted(S["profile"].get("needs") or [])) + "|" + S["lang"]
    return "turn2|" + hashlib.sha1(base.encode()).hexdigest()


def chat(session_id: str, message: str, profile: dict, lang: str, emit):
    S = SESSIONS.setdefault(session_id, {"history": [], "plan": None, "needs": []})
    S["profile"], S["lang"] = profile or {}, ("hi" if lang == "hi" else "en")
    key = _turn_key(message, S)
    with A._cache_lock:
        cached = A._load_cache().get(key)
    if cached:  # a repeated, rehearsed message replays instantly (the original run was real)
        for ev in cached["events"]:
            emit(ev)
        if cached.get("plan"):
            S["plan"], S["needs"] = cached["plan"], cached.get("needs", [])
        S["history"] += [{"role": "user", "content": message}, {"role": "assistant", "content": cached["final"]}]
        emit({"event": "done"})
        return
    events = []

    def rec(ev):
        events.append(ev); emit(ev)
    msgs = [{"role": "system", "content": ROOT_SYSTEM + "\nTraveller profile: " + ptext(S["profile"]) + "\nCurrent plan: " + plan_ctx(S) + "\n" + A._lang_rule(S["lang"])},
            *S["history"][-8:], {"role": "user", "content": message}]
    final = ""
    for hop in range(4):
        r = client.chat.completions.create(model=MODEL, messages=msgs, tools=[TRANSFER], temperature=0.2)
        m = r.choices[0].message
        if not m.tool_calls:
            final = (m.content or "").strip()
            break
        msgs.append(m)
        for tc in m.tool_calls[:3]:
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            name = args.get("agent_name") if args.get("agent_name") in FUNCS else "in_trip_agent"
            task = args.get("task") or message
            rec({"event": "agent", "name": "concierge", "status": "start", "note": f"transfer_to_agent: {name}"})
            rec({"event": "agent", "name": name, "status": "start"})
            try:
                summary = FUNCS[name](task, S, rec)
            except Exception as e:
                summary = f"{name} could not finish ({str(e)[:80]}). Suggest trying again."
                rec({"event": "message", "agent": name, "text": summary})
            rec({"event": "agent", "name": name, "status": "done"})
            msgs.append({"role": "tool", "tool_call_id": tc.id, "content": summary[:1800]})
    if not final:
        final = "I have finished what I could. Tell me what you would like next."
    rec({"event": "message", "agent": "concierge", "text": final})
    S["history"] += [{"role": "user", "content": message}, {"role": "assistant", "content": final}]
    with A._cache_lock:
        c = A._load_cache(); c[key] = {"events": events, "final": final, "plan": S.get("plan"), "needs": S.get("needs", [])}; A._save_cache(c)
    emit({"event": "done"})
