/* Halo Journeys Concierge frontend. Plain JS + ethers v6.
   LIVE mode: POST api/chat (NDJSON). SAMPLE mode: replay sample-session.json / dev-session.json.
   Chain reads and attestations (MetaMask) work in both modes. Chain logic is adapted from journeys.js. */
(function () {
  "use strict";
  const A = window.ACCESSREG;
  const $ = (id) => document.getElementById(id);
  const MQ_MOBILE = window.matchMedia("(max-width:1023px)");
  const REDUCED = window.matchMedia("(prefers-reduced-motion:reduce)");

  const FEATS = [
    ["step_free", "Step-free access"], ["ramp", "Ramp"], ["elevator", "Lift / elevator"], ["accessible_restroom", "Accessible toilet"],
    ["accessible_room", "Accessible room"], ["tactile_braille", "Tactile paving or Braille"], ["hearing_loop_sign", "Hearing loop or signing help"],
    ["quiet_space", "Quiet space"], ["assistance_service", "Staff assistance"], ["accessible_parking", "Accessible parking"],
  ];
  const ABI = [
    "function placeId(string placeName, string city) pure returns (bytes32)",
    "function summary(bytes32 id) view returns (uint32 attesters, uint32 confirmed, uint32[10] counts)",
    "function attest(string placeName, string city, uint16 features, bool venueConfirmed, string note)",
    "function totalAttestations() view returns (uint256)",
  ];
  const PROMPTS = [
    "Plan 3 days Pune to Goa, I use a wheelchair, budget 30000 rupees",
    "Suggest accessible destinations in India for a blind traveller",
    "The lift at my hotel is broken, what now?",
    "What should I pack and prepare?",
    "Review my plan for risks",
    "Draft messages to confirm accessibility with the hotel and airline",
  ];
  const ROLES = [
    ["concierge", "Understands you and hands off to specialists"],
    ["inspiration_agent", "Suggests accessible destinations"],
    ["planning_agent", "Builds your day-by-day plan"],
    ["booking_agent", "Prepares bookings (simulated)"],
    ["pre_trip_agent", "Packing, documents and preparation"],
    ["in_trip_agent", "Help while you are travelling"],
    ["post_trip_agent", "Feedback and traveller attestations"],
    ["accessibility_research_agent", "Researches access and cites sources"],
    ["mobility_preparation_agent", "Equipment and mobility preparation"],
    ["transit_support_agent", "Transfers and assistance on the way"],
    ["barrier_navigation_agent", "Finds options when something is not accessible"],
    ["notification_agent", "Reminders and alerts (simulated)"],
    ["accessibility_communication_agent", "Drafts messages to venues and airlines"],
    ["web_checkin_agent", "Web check-in (simulated)"],
    ["smart_guardrails_agent", "Reviews your plan for risk"],
  ];
  const NEEDS = [["wheelchair", "Wheelchair"], ["blind", "Blind or low vision"], ["deaf", "Deaf or hard of hearing"], ["cognitive", "Cognitive"], ["elderly", "Elderly"]];
  const NEED_SHORT = { wheelchair: "wheelchair", blind: "blind", deaf: "deaf", cognitive: "cognitive", elderly: "elderly" };

  const state = {
    live: false, tts: false, session: null, tok: 0, fast: false, replaying: false, replayP: null, sample: null,
    chain: new Map(), rpcIdx: 0, providers: {}, wallet: null, switching: null,
    arts: [], artSeq: 0, plans: [], counts: new Map(), active: new Map(), extraRoles: [],
    busy: false, abort: null, log: [], lastDay: "", profile: {}, lang: "en", thinkingEl: null, mic: null,
  };

  /* ---------- helpers ---------- */
  function h(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    for (const k in attrs || {}) {
      const v = attrs[k]; if (v == null || v === false) continue;
      if (k === "class") e.className = v; else if (k === "text") e.textContent = v;
      else if (k.startsWith("on")) e.addEventListener(k.slice(2), v); else e.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) e.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    return e;
  }
  const arr = (x) => (Array.isArray(x) ? x : []);
  const str = (x) => (x == null ? "" : String(x));
  const obj = (x) => (x && typeof x === "object" && !Array.isArray(x) ? x : {});
  const norm = (s) => str(s).toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
  const placeKey = (p) => ethers.id(norm(p.name) + "|" + norm(p.city));
  const safeUrl = (u) => { try { const x = new URL(u); return /^https?:$/.test(x.protocol) ? x.href : null; } catch (e) { return null; } };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const withTimeout = (p, ms, label) => Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error((label || "request") + " timed out")), ms))]);
  const short = (a) => a.slice(0, 6) + "…" + a.slice(-4);
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } },
    del(k) { try { localStorage.removeItem(k); } catch (e) { /* ignore */ } },
  };
  const wait = (ms) => (state.fast ? Promise.resolve() : sleep(ms));
  function toast(text, kind, link) {
    const t = h("div", { class: "toast " + (kind || "") }, text, link ? [" ", h("a", { href: link.href, target: "_blank", rel: "noopener noreferrer" }, link.text)] : null);
    $("toasts").append(t);
    setTimeout(() => t.remove(), kind === "err" ? 12000 : link ? 20000 : 6000);
  }
  function announce(text) { const l = $("sr-live"); l.textContent = ""; setTimeout(() => { l.textContent = text; }, 60); }

  /* ---------- icons ---------- */
  const IC = {
    mic: "M12 3a3 3 0 0 0-3 3v5a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3zM5 11a7 7 0 0 0 14 0M12 18v3",
    send: "M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z",
    stop: "M7 7h10v10H7z",
    edit: "M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z",
    plus: "M12 5v14M5 12h14",
    close: "M18 6L6 18M6 6l12 12",
    check: "M20 6L9 17l-5-5",
    user: "M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8z",
    speaker: "M11 5L6 9H2v6h4l5 4zM15.5 8.5a5 5 0 0 1 0 7M19 5a9 9 0 0 1 0 14",
    copy: "M9 9h11a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H9a2 2 0 0 1-2-2v-9a2 2 0 0 1 2-2zM5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1",
    chev: "M6 9l6 6 6-6",
    compass: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM16.2 7.8l-2.1 6.3-6.3 2.1 2.1-6.3z",
    star: "M12 2l3 7 7 .6-5.3 4.8 1.7 7.1L12 17.8 5.6 21.5l1.7-7.1L2 9.6 9 9z",
    wallet: "M3 7a2 2 0 0 1 2-2h14v4M3 7v11a2 2 0 0 0 2 2h16V9H5a2 2 0 0 1-2-2zM17 14h.01",
    list: "M9 11l3 3L22 4M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11",
    mail: "M4 4h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2zM22 6l-10 7L2 6",
    clock: "M12 22a10 10 0 1 0 0-20 10 10 0 0 0 0 20zM12 6v6l4 2",
    ticket: "M3 9a2 2 0 0 0 0 6v3h18v-3a2 2 0 0 0 0-6V6H3zM13 6v12",
    route: "M5 19a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM19 9a2 2 0 1 0 0-4 2 2 0 0 0 0 4zM7 17h6a3 3 0 0 0 0-6h-2a3 3 0 0 1 0-6h6",
    shield: "M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10zM9 12l2 2 4-4",
    alert: "M10.3 3.9L1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0zM12 9v4M12 17h.01",
    chat: "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z",
    bag: "M6 7h12l1 13H5zM9 7V5a3 3 0 0 1 6 0v2",
  };
  function ic(name, cls) {
    const ns = "http://www.w3.org/2000/svg", s = document.createElementNS(ns, "svg");
    s.setAttribute("viewBox", "0 0 24 24"); s.setAttribute("class", "ic" + (cls ? " " + cls : "")); s.setAttribute("aria-hidden", "true"); s.setAttribute("focusable", "false");
    const p = document.createElementNS(ns, "path"); p.setAttribute("d", IC[name] || IC.compass); s.append(p); return s;
  }
  function paintIcons(root) { (root || document).querySelectorAll("[data-ic]").forEach((el) => { el.replaceWith(ic(el.dataset.ic, el.className)); }); }

  /* ---------- names ---------- */
  const NAME_FIX = { web_checkin_agent: "Web check-in agent", concierge: "Concierge", pre_trip_agent: "Pre-trip agent", in_trip_agent: "In-trip agent", post_trip_agent: "Post-trip agent" };
  const MONO = { inspiration_agent: "In", planning_agent: "Pl", booking_agent: "Bk", pre_trip_agent: "Pr", in_trip_agent: "It", post_trip_agent: "Po", accessibility_research_agent: "Ar", mobility_preparation_agent: "Mp", transit_support_agent: "Ts", barrier_navigation_agent: "Bn", notification_agent: "No", accessibility_communication_agent: "Ac", web_checkin_agent: "Wc", smart_guardrails_agent: "Sg" };
  function pretty(n) {
    n = str(n) || "concierge"; if (NAME_FIX[n]) return NAME_FIX[n];
    const s = n.replace(/_/g, " ").trim(); return s.charAt(0).toUpperCase() + s.slice(1);
  }
  function mono(n) {
    n = str(n) || "concierge"; if (n === "concierge") return "C"; if (MONO[n]) return MONO[n];
    const w = n.replace(/_agent$/, "").split("_").filter(Boolean);
    return (w.length > 1 ? w[0][0] + w[1][0] : w[0].slice(0, 2)).replace(/^./, (c) => c.toUpperCase());
  }

  /* ---------- display prefs, tabs, tools ---------- */
  function initPrefs() {
    const d = document.documentElement;
    const apply = (s) => {
      if (s === "0") delete d.dataset.size; else d.dataset.size = s;
      document.querySelectorAll(".seg-b").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.size === s)));
    };
    apply(store.get("halo.j.size") || "0");
    document.querySelectorAll(".seg-b").forEach((b) => b.addEventListener("click", () => { apply(b.dataset.size); store.set("halo.j.size", b.dataset.size); }));
    const c = $("contrast");
    const setC = (on) => { if (on) d.dataset.contrast = "high"; else delete d.dataset.contrast; c.setAttribute("aria-pressed", String(on)); };
    setC(store.get("halo.j.contrast") === "1");
    c.addEventListener("click", () => { const on = c.getAttribute("aria-pressed") !== "true"; setC(on); store.set("halo.j.contrast", on ? "1" : "0"); });
    const tb = $("tools-btn"), tools = $("tools");
    const setOpen = (o) => { tools.dataset.open = String(o); tb.setAttribute("aria-expanded", String(o)); };
    tb.addEventListener("click", () => setOpen(tools.dataset.open !== "true"));
    document.addEventListener("click", (e) => { if (tools.dataset.open === "true" && !tools.contains(e.target) && !tb.contains(e.target)) setOpen(false); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && tools.dataset.open === "true") { setOpen(false); tb.focus(); } });
  }
  function tabKeys(list, onSelect) {
    list.addEventListener("keydown", (e) => {
      const tabs = Array.from(list.querySelectorAll('[role="tab"]')).filter((t) => t.offsetParent !== null);
      const i = tabs.indexOf(document.activeElement); if (i < 0) return;
      let n = -1;
      if (e.key === "ArrowRight") n = (i + 1) % tabs.length; else if (e.key === "ArrowLeft") n = (i - 1 + tabs.length) % tabs.length;
      else if (e.key === "Home") n = 0; else if (e.key === "End") n = tabs.length - 1;
      if (n >= 0) { e.preventDefault(); tabs[n].focus(); onSelect(tabs[n]); }
    });
  }
  function setView(v) {
    document.body.dataset.view = v;
    document.querySelectorAll(".tab-m").forEach((t) => { const on = t.dataset.view === v; t.setAttribute("aria-selected", String(on)); t.tabIndex = on ? 0 : -1; });
  }
  function setPane(p) {
    ["trip", "agents"].forEach((k) => {
      const on = k === p; $("ptab-" + k).setAttribute("aria-selected", String(on)); $("ptab-" + k).tabIndex = on ? 0 : -1; $("pane-" + k).hidden = !on;
    });
    $("jump").hidden = !(p === "trip" && state.arts.length);
  }
  function initTabs() {
    document.querySelectorAll(".tab-m").forEach((t) => t.addEventListener("click", () => setView(t.dataset.view)));
    tabKeys(document.querySelector(".tabs-m"), (t) => setView(t.dataset.view));
    $("ptab-trip").addEventListener("click", () => setPane("trip")); $("ptab-agents").addEventListener("click", () => setPane("agents"));
    tabKeys(document.querySelector(".ptabs"), (t) => setPane(t.id === "ptab-agents" ? "agents" : "trip"));
  }

  /* ---------- profile ---------- */
  function loadProfile() { try { const p = JSON.parse(store.get("halo.c.profile") || "{}"); return obj(p); } catch (e) { return {}; } }
  function profileForApi() {
    const p = state.profile, o = {};
    if (p.name) o.name = p.name;
    o.needs = arr(p.needs);
    if (p.aids) o.mobility_aids = p.aids;
    if (p.assistance) o.assistance_preferences = p.assistance;
    o.language = p.language || state.lang;
    if (p.home_city) o.home_city = p.home_city;
    if (p.budget_inr != null && p.budget_inr !== "") o.budget_inr = Number(p.budget_inr);
    if (p.ecn || p.ecp) o.emergency_contact = { name: p.ecn || "", phone: p.ecp || "" };
    if (p.email) o.email = p.email;
    return o;
  }
  function profileChipText() {
    const p = state.profile, needs = arr(p.needs);
    if (!p.name && !needs.length) return "My profile";
    const n = needs.length ? (NEED_SHORT[needs[0]] || needs[0]) + (needs.length > 1 ? " +" + (needs.length - 1) : "") : "";
    return [p.name || "Guest", n].filter(Boolean).join(" · ");
  }
  function paintProfileChip() {
    const t = profileChipText(); $("profile-chip-text").textContent = t;
    $("profile-btn").setAttribute("aria-label", "Edit my profile. " + (t === "My profile" ? "Not set yet." : t));
  }
  function fillProfileForm() {
    const p = state.profile, f = $("profile-form");
    f.name.value = p.name || ""; f.aids.value = p.aids || ""; f.assistance.value = p.assistance || ""; f.home_city.value = p.home_city || "";
    f.budget.value = p.budget_inr != null ? p.budget_inr : ""; f.ecn.value = p.ecn || ""; f.ecp.value = p.ecp || ""; f.email.value = p.email || "";
    f.querySelectorAll('input[name="need"]').forEach((i) => { i.checked = arr(p.needs).includes(i.value); });
    f.querySelectorAll('input[name="language"]').forEach((i) => { i.checked = i.value === (p.language || state.lang); });
  }
  function initProfile() {
    state.profile = loadProfile(); state.lang = state.profile.language === "hi" ? "hi" : (store.get("halo.c.lang") === "hi" ? "hi" : "en");
    $("pf-needs").replaceChildren(...NEEDS.map(([v, l]) => h("label", { class: "chip" }, h("input", { type: "checkbox", name: "need", value: v }), h("span", { text: l }))));
    paintProfileChip(); paintLang();
    $("profile-btn").addEventListener("click", (e) => { fillProfileForm(); openOverlay("drawer", e.currentTarget); });
    $("drawer-x").addEventListener("click", () => closeOverlay("drawer"));
    $("drawer-back").addEventListener("mousedown", (e) => { if (e.target === $("drawer-back")) closeOverlay("drawer"); });
    $("profile-form").addEventListener("submit", (e) => {
      e.preventDefault(); const f = e.currentTarget;
      const b = f.budget.value.trim();
      state.profile = {
        name: f.name.value.trim(), needs: Array.from(f.querySelectorAll('input[name="need"]:checked')).map((i) => i.value),
        aids: f.aids.value.trim(), assistance: f.assistance.value.trim(), language: (f.querySelector('input[name="language"]:checked') || {}).value || "en",
        home_city: f.home_city.value.trim(), budget_inr: b === "" ? null : Math.max(0, Number(b)), ecn: f.ecn.value.trim(), ecp: f.ecp.value.trim(), email: f.email.value.trim(),
      };
      store.set("halo.c.profile", JSON.stringify(state.profile));
      state.lang = state.profile.language === "hi" ? "hi" : "en"; store.set("halo.c.lang", state.lang); paintLang(); paintProfileChip();
      closeOverlay("drawer"); toast("Profile saved on this device.", "ok");
    });
    $("pf-clear").addEventListener("click", () => { state.profile = {}; store.del("halo.c.profile"); fillProfileForm(); paintProfileChip(); toast("Profile cleared."); });
  }

  /* ---------- overlays (focus trap) ---------- */
  const overlays = { drawer: { back: "drawer-back", box: "drawer", opener: null }, dlg: { back: "dlg-back", box: "dlg", opener: null } };
  function openOverlay(k, opener) {
    const o = overlays[k]; o.opener = opener || document.activeElement; $(o.back).hidden = false; document.body.style.overflow = "hidden";
    const first = $(o.box).querySelector("input,textarea,button"); (first || $(o.box)).focus();
  }
  function closeOverlay(k) {
    const o = overlays[k]; $(o.back).hidden = true; document.body.style.overflow = "";
    if (o.opener && o.opener.focus) o.opener.focus();
  }
  function overlayKeys() {
    document.addEventListener("keydown", (e) => {
      const k = !$("dlg-back").hidden ? "dlg" : !$("drawer-back").hidden ? "drawer" : null; if (!k) return;
      if (e.key === "Escape") { e.preventDefault(); if (k === "dlg") closeAttest(); else closeOverlay("drawer"); return; }
      if (e.key !== "Tab") return;
      const box = $(overlays[k].box);
      const f = Array.from(box.querySelectorAll('button,input,textarea,a[href],[tabindex]:not([tabindex="-1"])')).filter((x) => !x.disabled && !x.hidden && x.offsetParent !== null);
      if (!f.length) return; const first = f[0], last = f[f.length - 1], a = document.activeElement;
      if (!box.contains(a)) { e.preventDefault(); first.focus(); }
      else if (e.shiftKey && (a === first || a === box)) { e.preventDefault(); last.focus(); }
      else if (!e.shiftKey && a === last) { e.preventDefault(); first.focus(); }
    });
  }

  /* ---------- transcript primitives ---------- */
  const T = () => $("transcript");
  function scrollEnd(force) {
    const t = T(); if (force || t.scrollHeight - t.scrollTop - t.clientHeight < 200) t.scrollTop = t.scrollHeight;
  }
  function clearEmpty() { const e = $("empty"); if (e) e.remove(); }
  function ensureDay() {
    const key = new Date().toDateString(); if (state.lastDay === key) return; state.lastDay = key;
    const label = new Date().toLocaleDateString(undefined, { weekday: "long", day: "numeric", month: "long" });
    T().append(h("div", { class: "sep", role: "separator", "aria-label": label }, label));
  }
  function showEmpty() {
    T().replaceChildren(h("section", { class: "empty", id: "empty", "aria-labelledby": "empty-h" },
      h("span", { class: "mono", "aria-hidden": "true" }, "H"),
      h("h2", { id: "empty-h" }, "Where would you like to go?"),
      h("p", { class: "sub" }, "I am your travel concierge. Tell me what you need and I will plan, prepare and check your trip, and keep what the web claims apart from what travellers have verified."),
      h("div", { class: "prompts", role: "group", "aria-label": "Example requests" }, PROMPTS.map((p) => h("button", { type: "button", class: "prompt", onclick: () => submitText(p) }, p)))));
  }
  function addUser(text) {
    clearEmpty(); ensureDay();
    const bubble = h("div", { class: "bubble" }, text);
    T().append(h("div", { class: "msg user" }, h("span", { class: "sr" }, "You said: "), bubble)); scrollEnd(true); return bubble;
  }
  async function typeUser(text, tok) {
    clearEmpty(); ensureDay();
    const bubble = h("div", { class: "bubble" }), row = h("div", { class: "msg user" }, h("span", { class: "sr" }, "You said: "), bubble); T().append(row);
    const per = Math.min(26, 1400 / Math.max(1, text.length));
    if (state.fast) { bubble.textContent = text; scrollEnd(true); return; }
    for (let i = 1; i <= text.length; i++) { if (tok !== state.tok) return; bubble.textContent = text.slice(0, i); await sleep(per); if (state.fast) { bubble.textContent = text; break; } }
    scrollEnd(true);
  }
  function showThinking() {
    hideThinking();
    state.thinkingEl = h("div", { class: "thinking", role: "status" }, h("i", { class: "dot" }), h("i", { class: "dot" }), h("i", { class: "dot" }), h("span", { class: "sr" }, "The concierge is working"));
    T().append(state.thinkingEl); scrollEnd(true);
  }
  function hideThinking() { if (state.thinkingEl) { state.thinkingEl.remove(); state.thinkingEl = null; } }

  /* ---------- agent chips + agents panel ---------- */
  function lastHandoffs() {
    const l = T().lastElementChild; if (l && l.classList.contains("handoffs")) return l;
    const n = h("div", { class: "handoffs", role: "group", "aria-label": "Agent hand-offs" }); T().append(n); return n;
  }
  function chipLabel(name, done) { return pretty(name) + (done ? ", done" : ", working"); }
  function noteEl(note) { return note ? h("em", { text: "· " + note }) : null; }
  function agentEvent(ev) {
    hideThinking(); clearEmpty();
    const name = str(ev.name) || "concierge", status = ev.status === "done" ? "done" : "start";
    if (!ROLES.some((r) => r[0] === name) && !state.extraRoles.includes(name)) state.extraRoles.push(name);
    if (status === "start") {
      if (name !== "concierge" && state.active.has("concierge")) {   /* the concierge has handed off: its chip is complete */
        state.active.get("concierge").forEach((c) => { c.classList.remove("working"); c.classList.add("done"); c.setAttribute("aria-label", chipLabel("concierge", true)); }); state.active.delete("concierge");
      }
      const chip = h("span", { class: "hand working", "aria-label": chipLabel(name, false) }, h("i", { class: "dot" }), h("span", { class: "tick" }, ic("check")), h("b", {}, "→ " + pretty(name)), noteEl(ev.note));
      lastHandoffs().append(chip);
      if (!state.active.has(name)) state.active.set(name, []); state.active.get(name).push(chip);
      state.counts.set(name, (state.counts.get(name) || 0) + 1);
    } else {
      const list = state.active.get(name) || [], chip = list.shift();
      if (chip) {
        chip.classList.remove("working"); chip.classList.add("done"); chip.setAttribute("aria-label", chipLabel(name, true));
        if (ev.note && !chip.querySelector("em")) chip.append(noteEl(ev.note));
      } else {
        lastHandoffs().append(h("span", { class: "hand done", "aria-label": chipLabel(name, true) }, h("i", { class: "dot" }), h("span", { class: "tick" }, ic("check")), h("b", {}, "→ " + pretty(name)), noteEl(ev.note)));
        state.counts.set(name, (state.counts.get(name) || 0) + 1);
      }
      if (!list.length) state.active.delete(name);
    }
    renderAgents(); scrollEnd();
  }
  function closeAllChips() {
    state.active.forEach((list, name) => list.forEach((chip) => { chip.classList.remove("working"); chip.classList.add("done"); chip.setAttribute("aria-label", chipLabel(name, true)); }));
    state.active.clear(); renderAgents();
  }
  function renderAgents() {
    const roles = ROLES.concat(state.extraRoles.map((n) => [n, "Specialist"]));
    $("agents").replaceChildren(...roles.map(([n, d]) => {
      const on = state.active.has(n), c = state.counts.get(n) || 0;
      return h("li", { class: "ag" + (on ? " on" : "") },
        h("span", { class: "mono", "aria-hidden": "true" }, mono(n)),
        h("div", { class: "info" }, h("div", { class: "nm" }, pretty(n)), h("div", { class: "ds" }, d)),
        h("div", { class: "st" },
          on ? h("span", { class: "live" }, h("i", { class: "dot", "aria-hidden": "true" }), "Working") : h("span", { class: "idle", "aria-hidden": "true" }),
          h("span", { class: "cnt" + (c ? "" : " zero"), "aria-label": c + (c === 1 ? " time" : " times") + " this session" }, String(c))));
    }));
  }

  /* ---------- messages (streamed word by word, DOM nodes only) ---------- */
  function tokenise(text) {
    const segs = [];
    str(text).replace(/\r/g, "").split(/(\*\*[^*]+?\*\*)/).forEach((part) => {
      let bold = false; if (/^\*\*[^*]+\*\*$/.test(part)) { bold = true; part = part.slice(2, -2); }
      part.split(/(\n)/).forEach((p) => {
        if (p === "\n") segs.push({ br: true });
        else (p.match(/\s*\S+\s*/g) || []).forEach((w) => segs.push({ t: w, bold }));
      });
    });
    return segs;
  }
  function appendSeg(box, cur, seg) {
    if (seg.br) { box.append(document.createElement("br")); cur.node = null; return; }
    if (seg.bold) { if (!cur.node) { cur.node = document.createElement("strong"); box.append(cur.node); } cur.node.append(document.createTextNode(seg.t)); }
    else { cur.node = null; box.append(document.createTextNode(seg.t)); }
  }
  async function addMessage(agent, text, ctx) {
    hideThinking(); clearEmpty(); ensureDay();
    const name = str(agent) || "concierge";
    const bubble = h("div", { class: "bubble" });
    const col = h("div", { class: "col" }, h("div", { class: "who" }, pretty(name)), bubble);
    const row = h("div", { class: "msg agent" }, h("span", { class: "mono", "aria-hidden": "true" }, mono(name)), col);
    T().append(row);
    const segs = tokenise(text), cur = { node: null }, words = segs.filter((s) => !s.br).length || 1;
    if (ctx.instant || state.fast) segs.forEach((s) => appendSeg(bubble, cur, s));
    else {
      const per = Math.min(35, (ctx.maxMs || 6000) / words);
      let n = 0;
      for (const s of segs) {
        if (ctx.tok !== state.tok) return;
        appendSeg(bubble, cur, s);
        if (!s.br) { await sleep(per); if (++n % 3 === 0) scrollEnd(); if (state.fast) { /* skip rest */ } }
        if (state.fast) { segs.slice(segs.indexOf(s) + 1).forEach((r) => appendSeg(bubble, cur, r)); break; }
      }
    }
    const plain = segs.map((s) => (s.br ? "\n" : s.t)).join("").trim();
    const rb = h("button", { type: "button", class: "btn", "aria-pressed": "false", onclick: (e) => readAloud(plain, e.currentTarget) }, ic("speaker"), h("span", { class: "lbl" }, "Read aloud"));
    rb.setAttribute("aria-label", "Read aloud: message from " + pretty(name));
    col.append(h("div", { class: "msg-acts" }, rb, h("button", { type: "button", class: "btn", onclick: () => copyText(plain) }, ic("copy"), "Copy")));
    scrollEnd(true);
    if (!ctx.instant) announce(pretty(name) + " says: " + plain);
  }
  function errorRow(text) {
    hideThinking(); clearEmpty(); ensureDay();
    T().append(h("div", { class: "msg agent" }, h("span", { class: "mono", "aria-hidden": "true" }, "!"), h("div", { class: "col" }, h("div", { class: "bubble err", role: "alert" }, text))));
    scrollEnd(true);
  }

  /* ---------- read aloud ---------- */
  const speech = { stop: null, btn: null };
  function setRead(btn, on) { btn.setAttribute("aria-pressed", String(on)); const l = btn.querySelector(".lbl"); if (l) l.textContent = on ? "Stop reading" : "Read aloud"; }
  function stopSpeech() {
    if (speech.stop) { try { speech.stop(); } catch (e) { /* ignore */ } speech.stop = null; }
    try { window.speechSynthesis && speechSynthesis.cancel(); } catch (e) { /* ignore */ }
    if (speech.btn) { setRead(speech.btn, false); speech.btn = null; }
  }
  async function readAloud(text, btn) {
    if (speech.btn === btn) { stopSpeech(); return; }
    stopSpeech(); speech.btn = btn; setRead(btn, true);
    const done = () => { if (speech.btn === btn) stopSpeech(); };
    if (state.live && state.tts) {
      try {
        const r = await fetch("api/tts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
        if (!r.ok) throw new Error("tts " + r.status);
        const url = URL.createObjectURL(await r.blob()), au = new Audio(url);
        if (speech.btn !== btn) { URL.revokeObjectURL(url); return; }
        speech.stop = () => { au.pause(); URL.revokeObjectURL(url); };
        au.onended = done; au.onerror = () => { speech.stop = null; browserSpeak(text, btn, done); };
        await au.play(); return;
      } catch (e) { speech.stop = null; if (speech.btn !== btn) return; }
    }
    browserSpeak(text, btn, done);
  }
  function browserSpeak(text, btn, done) {
    if (!("speechSynthesis" in window)) { toast("Your browser cannot read aloud.", "err"); done(); return; }
    try {
      const u = new SpeechSynthesisUtterance(text); u.lang = state.lang === "hi" ? "hi-IN" : "en-IN"; u.onend = done; u.onerror = done;
      speechSynthesis.cancel(); speechSynthesis.speak(u);
    } catch (e) { done(); }
  }
  async function copyText(t) {
    try { await navigator.clipboard.writeText(t); toast("Copied.", "ok"); return; } catch (e) { /* fall through */ }
    try { const ta = h("textarea", { "aria-hidden": "true", style: "position:fixed;left:-999px" }); ta.value = t; document.body.append(ta); ta.select(); const ok = document.execCommand("copy"); ta.remove(); toast(ok ? "Copied." : "Could not copy. Select the text and copy it.", ok ? "ok" : "err"); }
    catch (e) { toast("Could not copy. Select the text and copy it.", "err"); }
  }

  /* ---------- chain reads (adapted from journeys.js) ---------- */
  function providerFor(url) { return state.providers[url] || (state.providers[url] = new ethers.JsonRpcProvider(url, A.chainId, { staticNetwork: true, batchMaxCount: 1 })); }
  const rpcList = () => (A.rpcs && A.rpcs.length ? A.rpcs : [A.rpc]);
  async function readOne(url, id) {
    const c = new ethers.Contract(A.address, ABI, providerFor(url));
    const r = await withTimeout(c.summary(id), 9000, "rpc");
    return { attesters: Number(r[0]), confirmed: Number(r[1]), counts: Array.from(r[2], Number) };
  }
  /* Never trust a single read: a zero answer is double-checked on a second node and the larger answer wins. */
  async function readSummary(id) {
    const urls = rpcList(); let best = null, ok = 0, last;
    for (let i = 0; i < urls.length * 3 && ok < Math.min(2, urls.length); i++) {
      const url = urls[(state.rpcIdx + i) % urls.length];
      try { const r = await readOne(url, id); ok++; if (!best || r.attesters > best.attesters) best = r; if (r.attesters > 0) break; }
      catch (e) { last = e; await sleep(250 * (i + 1)); }
    }
    if (!best) throw last || new Error("no RPC answered");
    state.rpcIdx = (state.rpcIdx + 1) % urls.length; return best;
  }
  async function loadChain(place, force) {
    const id = placeKey(place), cur = state.chain.get(id);
    if (cur && !force && (cur.status === "ok" || cur.status === "loading")) { renderPlaceState(place); return; }
    const prev = cur && cur.data;
    state.chain.set(id, { status: "loading", data: prev }); renderPlaceState(place);
    try { state.chain.set(id, { status: "ok", data: await readSummary(id) }); } catch (e) { state.chain.set(id, { status: "err", data: prev }); }
    renderPlaceState(place); updateChainStatus();
  }
  async function loadAllChain(places) {
    const q = places.slice();
    await Promise.all([0, 1, 2].map(async () => { while (q.length) await loadChain(q.shift()); }));
  }
  function updateChainStatus() {
    state.plans.forEach((pl) => {
      if (!pl.statusEl || !pl.statusEl.isConnected) return;
      const s = pl.places.map((p) => (state.chain.get(placeKey(p)) || {}).status);
      pl.statusEl.textContent = s.some((x) => x === "loading" || x === undefined) ? "Checking Monad for traveller attestations…"
        : s.some((x) => x === "err") ? "Some places could not be read from Monad right now." : "Traveller data read live from Monad.";
    });
  }
  function badgeFor(place, ch) {
    const acc = place.access || {}, src = arr(acc.sources).length, d = ch && ch.data;
    if (ch && ch.status === "loading" && !d) return { cls: "b-load", ic: "…", text: "Checking Monad…" };
    if (d && d.attesters >= 1 && d.confirmed >= 1) return { cls: "b-venue", ic: "✔", text: "Venue-confirmed" + (d.attesters > 1 ? " (" + d.attesters + " travellers)" : "") };
    if (d && d.attesters >= 2) return { cls: "b-comm", ic: "✔", text: "Community-verified (" + d.attesters + ")" };
    if (d && d.attesters === 1) return { cls: "b-one", ic: "✔", text: "1 traveller verified" };
    if (src >= 2 && acc.confidence !== "low") return { cls: "b-web", ic: "!", text: "Web-sourced only" };
    return { cls: "b-none", ic: "?", text: "Unverified" };
  }
  const yn = (v) => (v === "yes" ? "yes" : v === "no" ? "no" : "unknown");
  function featList(place, ch) {
    const f = obj(obj(place.access).features), d = ch && ch.data, n = d ? d.attesters : 0, full = [], quiet = [];
    FEATS.forEach(([k, label], i) => {
      const web = yn(f[k]), cnt = d ? d.counts[i] || 0 : null; let chain;
      if (!d) chain = ch && ch.status === "err" ? "Travellers: unavailable" : "Travellers: checking…";
      else if (n === 0) chain = "Travellers: none yet"; else chain = "Travellers: " + cnt + " of " + n + " confirmed";
      const hint = web === "yes" && d && n >= 1 && cnt === 0;
      const li = h("li", { class: "feat" }, h("b", { text: label }),
        h("span", { class: "tags" }, h("span", { class: "tag " + (web === "yes" ? "yes" : web === "no" ? "no" : "") }, "Web: " + web), h("span", { class: "tag chain " + (cnt > 0 ? "has" : "zero") }, chain)),
        hint ? h("p", { class: "gentle" }, "The web says yes, but travellers did not confirm this.") : null);
      (web === "unknown" && !cnt ? quiet : full).push(li);
    });
    const out = [h("ul", { class: "feats", "aria-label": "Features of " + place.name }, full)];
    if (quiet.length) out.push(h("details", { class: "more-f" }, h("summary", { text: "Show " + quiet.length + " features with no information yet" }), h("ul", { class: "feats" }, quiet)));
    return out;
  }
  function renderPlaceState(p) {
    const key = placeKey(p), ch = state.chain.get(key), b = badgeFor(p, ch), d = ch && ch.data;
    document.querySelectorAll('[data-pkey="' + key + '"]').forEach((el) => {
      const badge = el.querySelector('[data-role="badge"]'); badge.className = "badge " + b.cls; badge.dataset.ic = b.ic; badge.textContent = b.text;
      let line;
      if (!ch || (ch.status === "loading" && !d)) line = "Checking Monad…";
      else if (ch.status === "err" && !d) line = "Could not reach Monad right now, so traveller data is unavailable. This does not mean nobody has verified it.";
      else if (d.attesters === 0) line = "No traveller has attested this place yet. Be the first.";
      else line = d.attesters + (d.attesters === 1 ? " traveller has" : " travellers have") + " attested this place on-chain; " + d.confirmed + " said the venue confirmed it in writing.";
      el.querySelector('[data-role="chain-line"]').textContent = line;
      const fe = el.querySelector('[data-role="feats"]'), open = fe.querySelector("details") && fe.querySelector("details").open;
      fe.replaceChildren(...featList(p, ch)); if (open) fe.querySelector("details").open = true;
      el.querySelector('[data-role="retry"]').hidden = !(ch && ch.status === "err");
    });
    document.querySelectorAll('[data-badge="' + key + '"]').forEach((m) => { m.textContent = "· " + b.text; });
  }

  /* ---------- artifact renderers ---------- */
  const KINDS = {
    plan: { label: "Itinerary", icon: "compass" }, inspiration: { label: "Destinations", icon: "star" }, budget: { label: "Budget", icon: "wallet" },
    checklist: { label: "Checklist", icon: "list" }, drafts: { label: "Messages", icon: "mail" }, schedule: { label: "Reminders", icon: "clock" },
    checkin: { label: "Check-in", icon: "ticket" }, transit: { label: "Transit", icon: "route" }, guardrails: { label: "Plan review", icon: "shield" },
    barrier: { label: "Options", icon: "alert" }, feedback: { label: "Feedback", icon: "chat" }, booking: { label: "Booking", icon: "bag" },
  };
  const KIND = { transport: "Transport", stay: "Stay", place: "Place", food: "Food" };
  const PKIND = { airport: "Airport", station: "Station", hotel: "Hotel", attraction: "Attraction", restaurant: "Restaurant" };
  function money(n, cur) {
    const v = Number(n); if (!isFinite(v)) return str(n);
    try { return new Intl.NumberFormat("en-IN", { style: "currency", currency: cur || "INR", maximumFractionDigits: 0 }).format(v); } catch (e) { return "₹" + v.toLocaleString("en-IN"); }
  }
  const amt = (n, cur) => h("span", { class: "amt tnum" }, money(n, cur));
  const simTag = (d) => (d && d.simulated === true ? h("span", { class: "sim", title: "Nothing real was booked, sent or paid" }, "Simulated in this demo") : null);

  function lines(text) { return str(text).split("\n"); }
  function actRow(...btns) { return h("div", { class: "acts" }, btns.filter(Boolean)); }
  function waLink(text) { return h("a", { class: "btn sm", href: "https://wa.me/?text=" + encodeURIComponent(text), target: "_blank", rel: "noopener noreferrer" }, "Share on WhatsApp", h("span", { class: "sr" }, " (opens in a new tab)")); }
  function mailLink(subject, body) { return h("a", { class: "btn sm", href: "mailto:?subject=" + encodeURIComponent(subject || "") + "&body=" + encodeURIComponent(body || "") }, "Open in email app"); }
  const copyBtn = (t, label) => h("button", { type: "button", class: "btn sm", onclick: () => copyText(t) }, ic("copy"), label || "Copy");

  /* plan */
  const slug = (p) => norm(p.name + " " + p.city).replace(/ /g, "-");
  function renderPlan(d, art) {
    const places = arr(d.places).filter((p) => p && p.name), byName = new Map(places.map((p) => [p.name, p]));
    const needs = arr(obj(d.traveler).needs), notes = obj(d.traveler).notes;
    const pre = "a" + art.id + "-";
    const entry = { places, statusEl: h("span") }; state.plans = state.plans.filter((x) => x.art !== art.id); entry.art = art.id; state.plans.push(entry);
    const days = arr(d.days).map((day) => h("section", { class: "day", "aria-label": "Day " + day.day },
      h("h4", {}, h("span", { class: "dn" }, "Day " + str(day.day)), str(day.title)),
      h("ol", {}, arr(day.items).map((it) => {
        const p = it.place && byName.get(it.place);
        return h("li", { class: "it" },
          it.time ? h("span", { class: "t" }, it.time) : null,
          h("span", { class: "n" }, str(it.name), it.kind ? h("span", { class: "k" }, KIND[it.kind] || it.kind) : null),
          it.city ? h("span", { class: "c" }, it.city) : null,
          it.note ? h("span", { class: "nt" }, it.note) : null,
          p ? h("span", {}, h("a", { class: "more", href: "#" + pre + slug(p), onclick: (e) => { e.preventDefault(); gotoPlace(pre + slug(p)); } }, "Accessibility details", h("span", { class: "sr" }, " for " + p.name)), " ", h("span", { class: "mini", "data-badge": placeKey(p) })) : null);
      }))));
    const cards = places.map((p) => placeCard(p, pre));
    const tips = arr(d.tips);
    const el = h("div", {},
      d.summary ? h("p", { class: "plan-sum" }, d.summary) : null,
      needs.length || notes ? h("p", { class: "plan-for" }, (needs.length ? "Planned for: " + needs.join(", ") : "") + (notes ? (needs.length ? ". " : "") + notes : "")) : null,
      days.length ? h("h3", { class: "sub-h" }, "Day by day") : null, days,
      places.length ? [h("h3", { class: "sub-h" }, "Places and access"),
        h("div", { class: "legend" }, h("p", {}, h("strong", {}, "Verified"), " means real travellers recorded it on Monad. ", h("strong", {}, "Web-sourced"), " means found online, not yet confirmed by anyone. ", entry.statusEl)),
        h("div", { class: "places" }, cards)] : null,
      tips.length ? [h("h3", { class: "sub-h" }, "Tips for this trip"), h("ul", { class: "tips" }, tips.map((t) => h("li", { text: str(t) })))] : null);
    setTimeout(() => { places.forEach(renderPlaceState); updateChainStatus(); loadAllChain(places); }, 0);
    return el;
  }
  /* scroll inside the panel only (scrollIntoView would also scroll the locked page) */
  function scrollToEl(el) {
    const box = el.closest(".pane") || el.closest(".transcript"); if (!box) return;
    box.scrollTo({ top: box.scrollTop + el.getBoundingClientRect().top - box.getBoundingClientRect().top - 14, behavior: REDUCED.matches ? "auto" : "smooth" });
  }
  function gotoPlace(id) {
    const el = document.getElementById(id); if (!el) return;
    document.querySelectorAll(".place.hl").forEach((x) => x.classList.remove("hl")); el.classList.add("hl");
    scrollToEl(el);
    const t = el.querySelector("h4"); if (t) { t.tabIndex = -1; t.focus({ preventScroll: true }); }
  }
  function placeCard(p, pre) {
    const a = obj(p.access), id = pre + slug(p);
    const srcs = arr(a.sources).map((s) => ({ t: s.title || s.url, u: safeUrl(s.url) })).filter((s) => s.u);
    return h("article", { class: "place", id, "data-pkey": placeKey(p), "aria-labelledby": id + "-h" },
      h("div", { class: "ph" }, h("div", {}, h("h4", { id: id + "-h", text: p.name }), h("div", { class: "where" }, (PKIND[p.kind] || p.kind || "") + (p.city ? (p.kind ? " in " : "") + p.city : ""))),
        h("span", { class: "badge", "data-role": "badge" })),
      h("div", { class: "two" },
        h("div", { class: "panel claimed" }, h("h5", { text: "What the web says (claimed)" }), h("p", { text: a.summary || "No accessibility information was found." }),
          h("p", { class: "hint" }, "Confidence: " + (a.confidence || "unknown") + ". " + srcs.length + (srcs.length === 1 ? " source" : " sources") + "."),
          srcs.length ? h("ul", { class: "src" }, srcs.map((s) => h("li", {}, h("a", { href: s.u, target: "_blank", rel: "noopener noreferrer" }, s.t, h("span", { class: "sr" }, " (opens in a new tab)"))))) : null),
        h("div", { class: "panel verified", "aria-live": "polite" }, h("h5", { text: "What travellers attested on Monad (verified)" }), h("p", { "data-role": "chain-line", text: "Checking Monad…" }),
          h("p", { class: "hint", text: "Each tick below is a real traveller's on-chain statement." }))),
      h("div", { "data-role": "feats" }),
      h("div", { class: "acts" },
        p.draft ? h("button", { type: "button", class: "btn sm", "aria-expanded": "false", "aria-controls": id + "-draft", onclick: (e) => toggleDraft(e.currentTarget, id) }, "Draft a message to confirm") : null,
        h("button", { type: "button", class: "btn sm", onclick: (e) => openAttest(p, e.currentTarget) }, "I have been here: confirm what is accessible"),
        h("button", { type: "button", class: "btn sm", "data-role": "retry", hidden: true, onclick: () => loadChain(p, true) }, "Retry Monad check")),
      p.draft ? h("div", { class: "draft", id: id + "-draft", hidden: true }, draftBody(p.draft)) : null);
  }
  function draftBody(d) {
    const text = (d.subject ? d.subject + "\n\n" : "") + str(d.body);
    return [h("h5", {}, "Draft " + (d.channel === "whatsapp" ? "WhatsApp message" : "email")),
      d.subject ? h("p", {}, h("strong", {}, "Subject: "), d.subject) : null, h("pre", { text: str(d.body) }),
      actRow(copyBtn(text, "Copy message"), waLink(text), d.channel !== "whatsapp" ? mailLink(d.subject, d.body) : null)];
  }
  function toggleDraft(btn, id) {
    const box = document.getElementById(id + "-draft"), open = box.hidden; box.hidden = !open; btn.setAttribute("aria-expanded", String(open));
    btn.textContent = open ? "Hide the draft message" : "Draft a message to confirm";
  }

  /* inspiration */
  function renderInspiration(d) {
    const items = arr(d.places);
    return h("div", { class: "car", role: "list", "aria-label": "Suggested destinations" }, items.map((p) => h("button", { type: "button", class: "dcard", role: "listitem", onclick: () => useDestination(str(p.name)) },
      p.country ? h("span", { class: "dc" }, p.country) : null, h("span", { class: "dn" }, str(p.name)), p.why ? h("span", { class: "dw" }, p.why) : null,
      p.access_note ? h("span", { class: "da" }, p.access_note) : null, h("span", { class: "dgo" }, "Plan 3 days here →"))));
  }
  function useDestination(name) {
    const inp = $("composer-input"); inp.value = "Plan 3 days in " + name; autosize(); setView("chat"); inp.focus(); inp.setSelectionRange(inp.value.length, inp.value.length);
  }
  /* budget */
  function renderBudget(d) {
    const cur = d.currency || "INR", ls = arr(d.lines), mx = Math.max(1, ...ls.map((l) => Number(l.amount) || 0)), dis = arr(d.disability_costs);
    return h("div", {},
      h("ul", { class: "bl" }, ls.map((l) => h("li", {}, h("div", { class: "r1" }, h("span", {}, str(l.label)), amt(l.amount, cur)), l.note ? h("div", { class: "nt" }, l.note) : null,
        h("div", { class: "bar", "aria-hidden": "true" }, h("i", { style: "width:" + Math.round(((Number(l.amount) || 0) / mx) * 100) + "%" }))))),
      d.total != null ? h("div", { class: "total" }, h("span", {}, "Estimated total"), amt(d.total, cur)) : null,
      dis.length ? [h("h3", { class: "sub-h dis" }, "Disability-related costs"), h("ul", { class: "bl" }, dis.map((l) => h("li", {}, h("div", { class: "r1" }, h("span", {}, str(l.label)), amt(l.amount, cur)))))] : null,
      d.summary ? h("div", { class: "bsum" }, d.summary) : null);
  }
  /* checklist (ticks persisted per session) */
  function renderChecklist(d, art) {
    const key = "halo.c.chk." + state.session + "." + norm(art.title); let done = {};
    try { done = JSON.parse(store.get(key) || "{}"); } catch (e) { done = {}; }
    const groups = arr(d.groups), total = groups.reduce((n, g) => n + arr(g.items).length, 0);
    const label = h("span", { class: "tnum" }), fill = h("i"), prog = h("div", { class: "prog" }, label, h("div", { class: "bar", "aria-hidden": "true" }, fill));
    const upd = () => { const n = Object.keys(done).length; label.textContent = n + " of " + total + " done"; fill.style.width = (total ? (n / total) * 100 : 0) + "%"; art.progress = n + " of " + total + " done"; const cs = art.chatSum; if (cs) cs.textContent = art.progress; };
    const el = h("div", {}, prog, groups.map((g, gi) => h("section", { class: "cg" }, h("h4", {}, str(g.name)), h("ul", {}, arr(g.items).map((it, ii) => {
      const k = gi + "." + ii, cb = h("input", { type: "checkbox" }); cb.checked = !!done[k];
      cb.addEventListener("change", () => { if (cb.checked) done[k] = 1; else delete done[k]; store.set(key, JSON.stringify(done)); upd(); });
      return h("li", {}, h("label", { class: "ck" }, cb, h("span", {}, str(it))));
    })))));
    upd(); return el;
  }
  /* drafts */
  function renderDrafts(d) {
    return h("div", {}, arr(d.items).map((it) => {
      const text = (it.subject ? it.subject + "\n\n" : "") + str(it.body), wa = it.channel === "whatsapp";
      return h("article", { class: "dr" },
        h("div", { class: "to" }, it.to ? "To: " + it.to : "Message"),
        h("div", { class: "meta" }, h("span", { class: "pill mute" }, wa ? "WhatsApp" : "Email"), it.send_after ? h("span", {}, "Send after: " + it.send_after) : null),
        it.subject ? h("p", {}, h("strong", {}, "Subject: "), it.subject) : null, h("pre", { class: "msgbody", text: str(it.body) }),
        actRow(copyBtn(text, "Copy"), waLink(text), !wa ? mailLink(it.subject, it.body) : null));
    }));
  }
  function renderSchedule(d) {
    return h("ul", { class: "tl" }, arr(d.items).map((it) => h("li", {}, h("div", { class: "when" }, str(it.when)), h("div", {}, str(it.what)),
      h("div", { class: "meta" }, it.agent ? h("span", {}, pretty(it.agent)) : null, it.status ? h("span", { class: "pill " + (it.status === "simulated" ? "warn" : "info") }, it.status) : null))));
  }
  function renderCheckin(d) {
    const rows = [["Flight", d.flight], ["Opens", d.opens], ["Seat", d.seat]].filter((r) => r[1]);
    return h("div", {}, h("dl", { class: "kv" }, rows.flatMap(([k, v]) => [h("dt", {}, k), h("dd", {}, str(v))])), d.note ? h("p", { class: "bsum" }, d.note) : null);
  }
  function renderTransit(d) {
    return h("div", {}, arr(d.legs).map((l) => h("article", { class: "leg" },
      h("div", { class: "route" }, h("span", {}, str(l.from)), h("span", { "aria-hidden": "true" }, "→"), h("span", { class: "sr" }, " to "), h("span", {}, str(l.to)), l.mode ? h("span", { class: "pill mute" }, l.mode) : null),
      l.assistance ? h("p", {}, h("strong", {}, "Assistance: "), l.assistance) : null, l.tip ? h("p", { class: "hint" }, l.tip) : null)));
  }
  function renderGuardrails(d) {
    const lv = (x) => (x === "risk" || x === "caution" || x === "info" ? x : "info"), ov = d.overall === "ok" || d.overall === "caution" || d.overall === "risk" ? d.overall : "ok";
    const word = { ok: "Looks fine", caution: "Some cautions", risk: "Risks found", info: "Note", };
    return h("div", {}, h("div", { class: "gov" }, h("span", { class: "pill " + ov }, word[ov]), h("span", { class: "hint", style: "margin:0" }, arr(d.findings).length + " findings")),
      arr(d.findings).map((f) => h("div", { class: "fi " + lv(f.level) }, h("div", {}, h("p", {}, h("span", { class: "pill " + lv(f.level) }, lv(f.level)), " ", str(f.text)), f.fix ? h("p", { class: "fix" }, h("strong", {}, "What to do: "), f.fix) : null))));
  }
  function renderBarrier(d) {
    return h("div", {}, d.issue ? h("p", { class: "issue" }, d.issue) : null, arr(d.options).map((o) => h("article", { class: "opt" }, h("h4", {}, str(o.title)), o.detail ? h("p", {}, o.detail) : null, o.cost_hint ? h("p", { class: "hint" }, "Cost: ", h("span", { class: "tnum" }, o.cost_hint)) : null)));
  }
  function renderFeedback(d) {
    const s = d.attest_suggestion && obj(d.attest_suggestion), qs = arr(d.questions);
    return h("div", {}, qs.length ? h("ol", { class: "qs" }, qs.map((q) => h("li", { text: str(q) }))) : null,
      s && s.place ? h("div", {}, h("p", { class: "hint" }, "If you have been to " + s.place + ", your confirmation helps the next traveller. It is recorded on Monad."),
        h("button", { type: "button", class: "btn btn-primary", onclick: (e) => openAttest({ name: s.place, city: s.city || "" }, e.currentTarget, arr(s.features).map(Number)) }, "Confirm what was accessible at " + s.place)) : null);
  }
  function renderBooking(d) {
    return h("ul", { class: "bl" }, arr(d.items).map((it) => h("li", {}, h("div", { class: "r1" }, h("span", {}, str(it.label)), it.price != null && it.price !== "" ? (typeof it.price === "number" ? amt(it.price) : h("span", { class: "amt tnum" }, str(it.price))) : null), it.detail ? h("div", { class: "nt" }, it.detail) : null)));
  }
  function renderGeneric(d) {
    return h("div", { class: "generic" }, Object.keys(d).slice(0, 20).map((k) => h("div", {}, h("strong", {}, k + ": "), typeof d[k] === "object" ? JSON.stringify(d[k]) : str(d[k]))));
  }
  const RENDER = { plan: renderPlan, inspiration: renderInspiration, budget: renderBudget, checklist: renderChecklist, drafts: renderDrafts, schedule: renderSchedule, checkin: renderCheckin, transit: renderTransit, guardrails: renderGuardrails, barrier: renderBarrier, feedback: renderFeedback, booking: renderBooking };
  const n2 = (x, w) => x + " " + w + (x === 1 ? "" : "s");
  const SUMMARY = {
    plan: (d) => n2(arr(d.days).length, "day") + " · " + n2(arr(d.places).length, "place"),
    inspiration: (d) => n2(arr(d.places).length, "destination"),
    budget: (d) => (d.total != null ? "Total " + money(d.total, d.currency) : n2(arr(d.lines).length, "line")),
    checklist: (d) => n2(arr(d.groups).reduce((n, g) => n + arr(g.items).length, 0), "item"),
    drafts: (d) => n2(arr(d.items).length, "message") + " ready",
    schedule: (d) => n2(arr(d.items).length, "reminder"),
    checkin: (d) => [d.flight, d.opens && "opens " + d.opens].filter(Boolean).join(" · ") || "Web check-in",
    transit: (d) => n2(arr(d.legs).length, "leg"),
    guardrails: (d) => ({ ok: "Looks fine", caution: "Some cautions", risk: "Risks found" }[d.overall] || "Reviewed") + " · " + n2(arr(d.findings).length, "finding"),
    barrier: (d) => n2(arr(d.options).length, "option"),
    feedback: (d) => n2(arr(d.questions).length, "question"),
    booking: (d) => n2(arr(d.items).length, "item"),
  };

  /* ---------- artifact cards ---------- */
  function buildCard(art) {
    const k = KINDS[art.kind] || { label: "Result", icon: "compass" }, id = "art-" + art.id;
    let body; try { body = (RENDER[art.kind] || renderGeneric)(art.data, art); } catch (e) { body = h("p", { class: "hint" }, "This result could not be displayed."); }
    const toggle = h("button", { type: "button", class: "icon-btn art-toggle", "aria-expanded": "true", "aria-controls": id + "-b", "aria-label": "Collapse " + art.title, onclick: (e) => {
      const open = e.currentTarget.getAttribute("aria-expanded") !== "true"; e.currentTarget.setAttribute("aria-expanded", String(open)); e.currentTarget.setAttribute("aria-label", (open ? "Collapse " : "Expand ") + art.title); $(id + "-b").hidden = !open;
    } }, ic("chev"));
    return h("article", { class: "art", id, tabindex: "-1", "data-kind": art.kind, "aria-labelledby": id + "-h" },
      h("div", { class: "art-h" }, h("span", { class: "art-ic" }, ic(k.icon)), h("div", { class: "art-t" }, h("h3", { id: id + "-h" }, art.title),
        h("div", { class: "art-meta" }, h("span", {}, k.label), art.agent ? h("span", {}, "by " + pretty(art.agent)) : null, simTag(art.data))), toggle),
      h("div", { class: "art-body", id: id + "-b" }, body));
  }
  function compactCard(art) {
    const k = KINDS[art.kind] || { label: "Result", icon: "compass" };
    if (art.kind === "inspiration") {
      return h("div", { class: "art-in-chat wide" }, h("p", { class: "eyebrow", style: "margin:0 0 6px" }, art.title), renderInspiration(art.data));
    }
    let sum = ""; try { sum = (SUMMARY[art.kind] || (() => ""))(art.data); } catch (e) { /* ignore */ }
    const sEl = h("p", { class: "sum" }, sum); if (art.kind === "checklist") { art.chatSum = sEl; if (art.progress) sEl.textContent = art.progress; }
    const btn = h("button", { type: "button", class: "compact", onclick: () => showArtifact(art), "aria-label": "Open " + art.title + " in the Trip panel. " + sum },
      h("span", { class: "art-ic" }, ic(k.icon)), h("span", { class: "art-t" }, h("h3", {}, art.title), sEl, simTag(art.data)), h("span", { class: "go" }, "View →"));
    return h("div", { class: "art-in-chat" }, btn);
  }
  function updateTripChrome() {
    const n = state.arts.length;
    $("trip-empty").hidden = n > 0; $("trip-count").hidden = n === 0; $("trip-count").textContent = String(n);
    $("tab-trip").setAttribute("aria-label", "Trip" + (n ? ", " + n + (n === 1 ? " item" : " items") : ""));
    const j = $("jump"); j.replaceChildren(...state.arts.map((a) => h("a", { href: "#art-" + a.id, onclick: (e) => { e.preventDefault(); focusArt(a); } }, (KINDS[a.kind] || { label: a.title }).label)));
    j.hidden = !n || $("pane-trip").hidden;
  }
  function focusArt(art, noFlash) {
    if (!art.el) return; scrollToEl(art.el);
    if (!noFlash) { art.el.classList.remove("flash"); void art.el.offsetWidth; art.el.classList.add("flash"); }
  }
  function showArtifact(art) {
    setPane("trip"); if (MQ_MOBILE.matches) setView("trip");
    setTimeout(() => { focusArt(art); art.el && art.el.focus({ preventScroll: true }); }, 30);
  }
  function addArtifact(ev, ctx) {
    hideThinking(); clearEmpty();
    const kind = str(ev.kind) || "note", data = obj(ev.data), title = str(ev.title) || (KINDS[kind] || { label: "Result" }).label;
    let art = state.arts.find((a) => a.kind === kind && a.title === title), isNew = !art;
    if (!art) { art = { id: ++state.artSeq, kind, title, data, agent: ev.agent }; state.arts.push(art); } else { art.data = data; art.agent = ev.agent; }
    const el = buildCard(art);
    if (isNew) $("arts").append(el); else art.el.replaceWith(el); art.el = el;
    updateTripChrome();
    ensureDay(); T().append(compactCard(art)); scrollEnd(true);
    if (!ctx.instant && !MQ_MOBILE.matches) { setPane("trip"); setTimeout(() => focusArt(art), 120); }
  }

  /* ---------- event pipeline ---------- */
  async function handleEvent(ev, ctx) {
    if (!ev || ctx.tok !== state.tok) return;
    switch (ev.event) {
      case "agent": agentEvent(ev); break;
      case "message": await addMessage(ev.agent, ev.text, ctx); break;
      case "artifact": addArtifact(ev, ctx); break;
      case "error": errorRow(str(ev.text) || "Something went wrong."); break;
      default: break;
    }
  }
  const EVDELAY = { agent: (e) => (e.status === "done" ? 800 : 500), message: () => 300, artifact: () => 600 };
  async function playEvents(events, ctx) {
    for (const ev of events) {
      if (ctx.tok !== state.tok) return;
      if (!ctx.instant) await wait((EVDELAY[ev.event] || (() => 0))(ev));
      await handleEvent(ev, ctx);
    }
    if (ctx.tok === state.tok) finishTurn();
  }
  function finishTurn() { hideThinking(); closeAllChips(); setBusy(false); }
  function setBusy(b) {
    state.busy = b; const s = $("send");
    s.replaceChildren(ic(b && state.live ? "stop" : "send")); s.setAttribute("aria-label", b && state.live ? "Stop the concierge" : "Send message");
    $("main").setAttribute("aria-busy", String(b));
  }

  /* ---------- chat ---------- */
  function saveLog() {
    if (!state.live) return;
    try { const s = JSON.stringify(state.log.slice(-8)); if (s.length < 400000) store.set("halo.c.log." + state.session, s); } catch (e) { /* ignore */ }
  }
  async function sendLive(text) {
    const tok = state.tok; addUser(text); showThinking(); setBusy(true);
    const turn = { user: text, events: [] }; state.log.push(turn);
    const ac = state.abort = new AbortController(), ctx = { tok, maxMs: 4000 }; let q = Promise.resolve();
    try {
      const res = await fetch("api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, signal: ac.signal,
        body: JSON.stringify({ session: state.session, message: text, profile: profileForApi(), lang: state.lang }) });
      if (!res.ok || !res.body) throw new Error("The concierge answered with status " + res.status + ".");
      const rd = res.body.getReader(), dec = new TextDecoder(); let buf = "";
      const handle = (line) => {
        if (!line.trim()) return; let m; try { m = JSON.parse(line); } catch (e) { return; }
        turn.events.push(m); q = q.then(() => handleEvent(m, ctx)).catch(() => {});
      };
      for (;;) {
        const { done, value } = await rd.read(); if (done) break;
        buf += dec.decode(value, { stream: true });
        let i; while ((i = buf.indexOf("\n")) >= 0) { handle(buf.slice(0, i)); buf = buf.slice(i + 1); }
      }
      handle(buf); await q;
    } catch (e) {
      await q.catch(() => {});
      if (e.name === "AbortError") toast("Stopped."); else if (tok === state.tok) errorRow("I could not reach the concierge. " + (e.message || "") + " Please try again.");
    } finally { if (tok === state.tok) { finishTurn(); state.abort = null; saveLog(); $("composer-input").focus(); } }
  }
  async function sendSample(text) {
    const tok = state.tok;
    if (state.replayP) { state.fast = true; await state.replayP; state.fast = false; if (tok !== state.tok) return; }
    const turns = arr(obj(state.sample).turns), hit = turns.find((t) => norm(t.user) === norm(text));
    setBusy(true); addUser(text); showThinking();
    if (hit) { await wait(500); await playEvents(arr(hit.events), { tok, maxMs: 7000 }); return; }
    await sleep(700);
    hideThinking(); await addMessage("concierge", "Run the concierge locally to chat live. This page replays a recorded session, so I cannot answer new questions here, but you can press **Replay** to watch it again.", { tok, maxMs: 4000 });
    finishTurn();
  }
  function submitText(text) {
    text = str(text).trim(); if (!text) return;
    if (state.busy && state.live) return;
    $("composer-input").value = ""; autosize(); stopSpeech();
    if (MQ_MOBILE.matches) setView("chat");
    if (state.live) sendLive(text); else sendSample(text);
  }
  function autosize() { const t = $("composer-input"); t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 150) + "px"; }
  function initComposer() {
    const inp = $("composer-input");
    inp.addEventListener("input", autosize);
    inp.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); submitText(inp.value); } });
    $("composer").addEventListener("submit", (e) => {
      e.preventDefault();
      if (state.busy && state.live) { if (state.abort) state.abort.abort(); return; }
      submitText(inp.value);
    });
  }

  /* ---------- voice input ---------- */
  function paintLang() {
    const b = $("lang-btn"), hi = state.lang === "hi"; b.textContent = hi ? "हि" : "EN";
    b.setAttribute("aria-label", "Speaking language: " + (hi ? "Hindi" : "English (India)") + ". Press to switch to " + (hi ? "English." : "Hindi."));
  }
  function initMic() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition; if (!SR) return;
    const btn = $("mic"), lb = $("lang-btn"), st = $("mic-status"), note = $("composer-note"); btn.hidden = false; lb.hidden = false;
    const say = (t) => { st.textContent = t; note.textContent = t; note.hidden = !t; };
    lb.addEventListener("click", () => { state.lang = state.lang === "hi" ? "en" : "hi"; store.set("halo.c.lang", state.lang); paintLang(); });
    btn.addEventListener("click", () => {
      if (state.mic) { try { state.mic.stop(); } catch (e) { /* ignore */ } return; }
      const rec = state.mic = new SR(); rec.lang = state.lang === "hi" ? "hi-IN" : "en-IN"; rec.interimResults = false; rec.continuous = false;
      rec.onstart = () => { btn.setAttribute("aria-pressed", "true"); btn.classList.add("mic-on"); btn.setAttribute("aria-label", "Stop listening"); say("Listening. Speak now."); };
      rec.onresult = (e) => { let t = ""; for (let i = e.resultIndex; i < e.results.length; i++) t += e.results[i][0].transcript; t = t.trim(); if (t) { const ta = $("composer-input"); ta.value = (ta.value.trim() ? ta.value.trim() + " " : "") + t; autosize(); say("Added: " + t); } };
      rec.onerror = (e) => say(e.error === "not-allowed" ? "Microphone permission was denied. You can type instead." : e.error === "no-speech" ? "I did not hear anything. Try again." : "Voice input stopped (" + e.error + "). You can type instead.");
      rec.onend = () => { state.mic = null; btn.setAttribute("aria-pressed", "false"); btn.classList.remove("mic-on"); btn.setAttribute("aria-label", "Speak your message"); setTimeout(() => { if (!state.mic) say(""); }, 4000); };
      try { rec.start(); } catch (e) { state.mic = null; say("Could not start the microphone."); }
    });
  }

  /* ---------- attest dialog + MetaMask (adapted from journeys.js) ---------- */
  let dlgPlace = null, busyAtt = false;
  function openAttest(place, opener, pre) {
    dlgPlace = place;
    $("dlg-h").textContent = "I have been here: " + place.name;
    $("dlg-d").textContent = "Tick only what you saw yourself in " + (place.city || "this place") + ". This records your statement on Monad and costs a tiny amount of test gas.";
    const sel = new Set(arr(pre));
    $("att-feats").replaceChildren(...FEATS.map(([k, label], i) => { const cb = h("input", { type: "checkbox", name: "af", value: String(i) }); cb.checked = sel.has(i); return h("label", { class: "check" }, cb, h("span", { text: label })); }));
    $("att-venue").checked = false; $("att-note").value = ""; $("att-count").textContent = "0 / 280";
    $("att-err").hidden = true; $("att-status").textContent = ""; $("att-go").disabled = false; $("att-go").hidden = false; $("att-close").textContent = "Close";
    openOverlay("dlg", opener);
  }
  function closeAttest() {
    if (busyAtt && !confirm("A transaction is in progress. Close this window anyway? The transaction may still complete.")) return;
    closeOverlay("dlg");
  }
  function dlgSay(text, ok) { $("att-status").replaceChildren(h("span", { class: ok ? "ok" : "" }, text)); }
  function initWalletBtn() {
    const b = $("wallet-btn"); if (!b) return;
    const label = b.querySelector(".lbl");
    b.addEventListener("click", async () => {
      b.disabled = true; label.textContent = "Connecting…";
      try {
        const a = await ensureWallet();
        label.textContent = "Monad · " + short(a); b.classList.add("on");
        toast("Wallet connected on Monad testnet: " + short(a), "ok");
      } catch (e) {
        label.textContent = "Connect wallet";
        const rejected = e && (e.code === 4001 || e.code === "ACTION_REJECTED");
        toast(rejected ? "The wallet request was closed. Press Connect wallet to try again." : ((e && e.message) || "Could not connect the wallet."), "err");
      } finally { b.disabled = false; }
    });
  }
  async function ensureWallet() {
    const eth = window.ethereum;
    if (!eth) throw new Error("No wallet found. Install MetaMask in this browser, then try again.");
    dlgSay("Step 1 of 4: connecting to your wallet. Please approve in MetaMask…"); toast("Connecting to your wallet…");
    const accs = await eth.request({ method: "eth_requestAccounts" });
    if (!accs || !accs[0]) throw new Error("No account was shared by the wallet.");
    state.wallet = { account: accs[0].toLowerCase() };
    const hex = "0x" + A.chainId.toString(16);
    dlgSay("Step 2 of 4: switching your wallet to Monad testnet…"); toast("Switching to Monad testnet…");
    state.switching = hex;
    try {
      const cur = await eth.request({ method: "eth_chainId" });
      if (String(cur).toLowerCase() !== hex) {
        try { await eth.request({ method: "wallet_switchEthereumChain", params: [{ chainId: hex }] }); }
        catch (e) {
          if (e && (e.code === 4902 || /unrecognized|not added|add the chain/i.test(e.message || ""))) {
            await eth.request({ method: "wallet_addEthereumChain", params: [{ chainId: hex, chainName: "Monad Testnet", nativeCurrency: { name: "MON", symbol: "MON", decimals: 18 }, rpcUrls: rpcList(), blockExplorerUrls: [A.explorer] }] });
          } else throw e;
        }
      }
    } finally { setTimeout(() => { state.switching = null; }, 800); }
    return accs[0];
  }
  /* MetaMask fires accountsChanged/chainChanged during a normal connect: ignore unless something really changed. Never reload. */
  function watchWallet() {
    const eth = window.ethereum; if (!eth || !eth.on) return;
    eth.on("accountsChanged", (a) => {
      if (!state.wallet) return; const n = a && a[0] ? a[0].toLowerCase() : null;
      if (n === state.wallet.account) return;
      if (!n) { state.wallet = null; toast("Wallet disconnected."); } else { state.wallet.account = n; toast("Wallet account changed to " + short(n) + "."); }
    });
    eth.on("chainChanged", (c) => {
      if (!state.wallet || state.switching) return;
      if (String(c).toLowerCase() !== "0x" + A.chainId.toString(16)) toast("Your wallet is no longer on Monad testnet. We will switch it again when you submit.");
    });
  }
  async function pollReceipt(hash) {
    const urls = rpcList(), t0 = Date.now();
    for (let i = 0; Date.now() - t0 < 90000; i++) {
      try { const r = await withTimeout(providerFor(urls[i % urls.length]).getTransactionReceipt(hash), 8000, "rpc"); if (r) return r; } catch (e) { /* try next RPC */ }
      await sleep(1200);
    }
    return null;
  }
  async function submitAttest(ev) {
    ev.preventDefault(); if (busyAtt) return;
    const ticked = Array.from($("att-feats").querySelectorAll("input:checked")).map((i) => Number(i.value)), e = $("att-err"); e.hidden = true;
    if (!ticked.length) { e.hidden = false; e.textContent = "Please tick at least one thing that was accessible."; return; }
    const note = $("att-note").value.trim().slice(0, 280), venue = $("att-venue").checked, place = dlgPlace;
    const mask = ticked.reduce((m, i) => m | (1 << i), 0);
    busyAtt = true; $("att-go").disabled = true;
    try {
      const from = await ensureWallet();
      const data = new ethers.Interface(ABI).encodeFunctionData("attest", [norm(place.name), norm(place.city), mask, venue, note]);
      dlgSay("Step 3 of 4: please confirm the transaction in your wallet…"); toast("Waiting for you to confirm in your wallet…");
      const before = (state.chain.get(placeKey(place)) || {}).data;
      const hash = await window.ethereum.request({ method: "eth_sendTransaction", params: [{ from, to: A.address, data }] });
      const link = A.explorer + "/tx/" + hash;
      dlgSay("Step 4 of 4: transaction sent. Waiting for Monad to confirm it (up to 90 seconds)…"); toast("Transaction sent. Waiting for confirmation…", "", { href: link, text: "View on Monadscan" });
      const rc = await pollReceipt(hash);
      if (!rc) { dlgSay("Sent, but we could not confirm it yet. Check the link below."); $("att-status").append(" ", h("a", { href: link, target: "_blank", rel: "noopener noreferrer" }, "View transaction")); toast("Not confirmed yet. It may still go through.", "err", { href: link, text: "View on Monadscan" }); return; }
      if (rc.status !== 1) throw new Error("The transaction failed on-chain. Nothing was recorded.");
      dlgSay("Done. Your statement is recorded on Monad. Thank you.", true);
      $("att-status").append(" ", h("a", { href: link, target: "_blank", rel: "noopener noreferrer" }, "View transaction on Monadscan", h("span", { class: "sr" }, " (opens in a new tab)")));
      toast("Attestation confirmed on Monad.", "ok", { href: link, text: "View on Monadscan" });
      $("att-go").hidden = true; refreshAfterAttest(place, before);
    } catch (err) {
      const m = err && (err.shortMessage || err.message) || String(err);
      const rejected = err && (err.code === 4001 || err.code === "ACTION_REJECTED" || /reject|denied/i.test(m));
      const text = rejected ? "You declined in your wallet, so nothing was sent." : /insufficient/i.test(m) ? "Your wallet does not have enough test MON to pay the network fee. Get some from the Monad testnet faucet and try again." : "Could not complete: " + m;
      dlgSay(text); toast(text, "err"); $("att-go").disabled = false;
    } finally { busyAtt = false; }
  }
  async function refreshAfterAttest(place, before) {
    const id = placeKey(place);
    for (let i = 0; i < 6; i++) {
      await loadChain(place, true); const c = state.chain.get(id);
      if (c && c.data && (!before || c.data.attesters > before.attesters)) return;
      await sleep(1500);
    }
  }
  function initDialog() {
    $("att-form").addEventListener("submit", submitAttest);
    $("att-close").addEventListener("click", closeAttest);
    $("att-note").addEventListener("input", (e) => { $("att-count").textContent = e.target.value.length + " / 280"; });
    $("dlg-back").addEventListener("mousedown", (e) => { if (e.target === $("dlg-back")) closeAttest(); });
  }

  /* ---------- sessions, replay, boot ---------- */
  const newId = () => "s" + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
  function paintSession() { $("session-label").textContent = "Session " + state.session.slice(-6); }
  function resetUI(keepEmpty) {
    state.tok++; state.fast = false; state.replaying = false; state.replayP = null;
    if (state.abort) { try { state.abort.abort(); } catch (e) { /* ignore */ } state.abort = null; }
    stopSpeech(); state.arts = []; state.plans = []; state.active.clear(); state.counts.clear(); state.log = []; state.lastDay = ""; state.thinkingEl = null;
    $("arts").replaceChildren(); T().replaceChildren(); updateTripChrome(); renderAgents(); setBusy(false);
    if (keepEmpty) showEmpty();
    if (MQ_MOBILE.matches) setView("chat"); setPane("trip");
  }
  function newSession() {
    store.del("halo.c.log." + state.session);
    state.session = newId(); store.set("halo.c.session", state.session); paintSession(); resetUI(true);
    if (!state.live && state.sample) $("banner").hidden = false;
    $("composer-input").focus();
  }
  async function replay() {
    resetUI(false); const tok = state.tok, turns = arr(obj(state.sample).turns);
    state.replaying = true; const ctxBase = { tok, maxMs: 9000 };
    state.replayP = (async () => {
      for (let i = 0; i < turns.length; i++) {
        if (tok !== state.tok) return;
        await wait(i === 0 ? 700 : 1400); if (tok !== state.tok) return;
        await typeUser(str(turns[i].user), tok); setBusy(true); showThinking();
        await wait(600);
        await playEvents(arr(turns[i].events), ctxBase);
      }
      if (tok === state.tok) { state.replaying = false; state.replayP = null; state.fast = false; }
    })();
    return state.replayP;
  }
  async function restoreLog() {
    let log = []; try { log = JSON.parse(store.get("halo.c.log." + state.session) || "[]"); } catch (e) { log = []; }
    if (!Array.isArray(log) || !log.length) { showEmpty(); return; }
    const tok = state.tok;
    for (const turn of log) {
      addUser(str(turn.user)); state.log.push(turn);
      for (const ev of arr(turn.events)) await handleEvent(ev, { tok, instant: true });
    }
    finishTurn(); scrollEnd(true);
  }
  async function loadSample() {
    for (const f of ["sample-session.json", "dev-session.json"]) {
      try { const r = await fetch(f, { cache: "no-cache" }); if (r.ok) { const j = await r.json(); if (j && Array.isArray(j.turns)) return j; } } catch (e) { /* next */ }
    }
    return null;
  }
  async function boot() {
    paintIcons(); initPrefs(); initTabs(); initComposer(); initProfile(); initMic(); initDialog(); overlayKeys(); watchWallet(); initWalletBtn();
    state.session = store.get("halo.c.session") || newId(); store.set("halo.c.session", state.session); paintSession(); renderAgents(); setPane("trip");
    $("new-btn").addEventListener("click", newSession);
    $("replay-btn").addEventListener("click", () => { if (state.sample) replay(); });
    try {
      const r = await withTimeout(fetch("api/config", { cache: "no-store" }), 2500, "config");
      const c = r.ok ? await r.json() : null; if (c && c.live === true) { state.live = true; state.tts = !!c.tts; }
    } catch (e) { /* sample mode */ }
    document.body.dataset.mode = state.live ? "live" : "sample"; setBusy(false);
    if (state.live) { await restoreLog(); return; }
    $("banner").hidden = false; state.sample = await loadSample();
    if (!state.sample) { $("banner-text").textContent = "The recorded session could not be loaded. Run the concierge locally to chat live."; $("replay-btn").hidden = true; showEmpty(); return; }
    replay();
  }
  window.haloConcierge = { emit: (ev) => handleEvent(ev, { tok: state.tok, instant: true }), state };
  if (!window.ethers || !A) { document.addEventListener("DOMContentLoaded", () => { const m = $("banner"); m.hidden = false; $("banner-text").textContent = "This page could not load its blockchain libraries."; }); }
  else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
