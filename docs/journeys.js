/* Halo Journeys frontend. Plain JS + ethers v6. LIVE mode talks to /api/plan and /api/tts; SAMPLE mode shows sample-plan.json.
   Chain badges (reads) and attestations (writes, MetaMask) work in both modes. */
(function () {
  "use strict";
  const A = window.ACCESSREG;
  const $ = (id) => document.getElementById(id);
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
  const EXAMPLES = [
    ["3 days Pune to Goa, I use a wheelchair, budget 30000 rupees", ["wheelchair"]],
    ["A weekend in Jaipur for my blind mother and me, we like heritage places, budget 20000 rupees", ["blind", "elderly"]],
    ["4 days Delhi to Agra and back, I am deaf, I need clear written instructions", ["deaf"]],
    ["A calm 2 day trip from Mumbai to Lonavala with my son who finds crowds hard", ["cognitive"]],
  ];
  const state = { live: false, tts: false, plan: null, chain: new Map(), abort: null, rpcIdx: 0, providers: {}, wallet: null, speaking: null };

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
  const norm = (s) => String(s == null ? "" : s).toLowerCase().replace(/[^a-z0-9 ]/g, " ").replace(/\s+/g, " ").trim();
  const placeKey = (p) => ethers.id(norm(p.name) + "|" + norm(p.city));
  const safeUrl = (u) => { try { const x = new URL(u); return /^https?:$/.test(x.protocol) ? x.href : null; } catch (e) { return null; } };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const withTimeout = (p, ms, label) => Promise.race([p, new Promise((_, rej) => setTimeout(() => rej(new Error((label || "request") + " timed out")), ms))]);
  const short = (a) => a.slice(0, 6) + "…" + a.slice(-4);
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* ignore */ } },
  };
  function toast(text, kind, link) {
    const t = h("div", { class: "j-toast " + (kind || "") }, text, link ? [" ", h("a", { href: link.href, target: "_blank", rel: "noopener noreferrer" }, link.text)] : null);
    $("toasts").append(t);
    setTimeout(() => t.remove(), kind === "err" ? 12000 : link ? 20000 : 7000);
  }

  /* ---------- accessibility toggles ---------- */
  function initPrefs() {
    const d = document.documentElement;
    const size = store.get("halo.j.size") || "0";
    const apply = (s) => {
      if (s === "0") delete d.dataset.size; else d.dataset.size = s;
      document.querySelectorAll("[data-size].j-seg-b").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.size === s)));
    };
    apply(size);
    document.querySelectorAll(".j-seg-b").forEach((b) => b.addEventListener("click", () => { apply(b.dataset.size); store.set("halo.j.size", b.dataset.size); }));
    const c = $("contrast");
    const setC = (on) => { if (on) d.dataset.contrast = "high"; else delete d.dataset.contrast; c.setAttribute("aria-pressed", String(on)); };
    setC(store.get("halo.j.contrast") === "1");
    c.addEventListener("click", () => { const on = c.getAttribute("aria-pressed") !== "true"; setC(on); store.set("halo.j.contrast", on ? "1" : "0"); });
  }

  /* ---------- on-chain reads (rotating public RPCs, never trusting one call) ---------- */
  function providerFor(url) {
    return state.providers[url] || (state.providers[url] = new ethers.JsonRpcProvider(url, A.chainId, { staticNetwork: true, batchMaxCount: 1 }));
  }
  const rpcList = () => (A.rpcs && A.rpcs.length ? A.rpcs : [A.rpc]);
  async function readOne(url, id) {
    const c = new ethers.Contract(A.address, ABI, providerFor(url));
    const r = await withTimeout(c.summary(id), 9000, "rpc");
    return { attesters: Number(r[0]), confirmed: Number(r[1]), counts: Array.from(r[2], Number) };
  }
  /* Ask a node; empty/failed answers rotate to the next node. A zero answer is double-checked on a second node
     (a lagging node can say "zero" for something just attested) and the larger answer wins. */
  async function readSummary(id) {
    const urls = rpcList(); let best = null, ok = 0, last;
    for (let i = 0; i < urls.length * 3 && ok < Math.min(2, urls.length); i++) {
      const url = urls[(state.rpcIdx + i) % urls.length];
      try {
        const r = await readOne(url, id); ok++;
        if (!best || r.attesters > best.attesters) best = r;
        if (r.attesters > 0) break;
      } catch (e) { last = e; await sleep(250 * (i + 1)); }
    }
    if (!best) throw last || new Error("no RPC answered");
    state.rpcIdx = (state.rpcIdx + 1) % urls.length;
    return best;
  }
  async function loadChain(place, force) {
    const id = placeKey(place);
    const cur = state.chain.get(id);
    if (cur && !force && (cur.status === "ok" || cur.status === "loading")) return;
    const prev = cur && cur.data;
    state.chain.set(id, { status: "loading", data: prev });
    renderPlaceState(place);
    try {
      const data = await readSummary(id);
      state.chain.set(id, { status: "ok", data });
    } catch (e) { state.chain.set(id, { status: "err", data: prev }); }
    renderPlaceState(place);
    updateChainStatus();
  }
  async function loadAllChain() {
    const q = state.plan.places.slice();
    await Promise.all([0, 1, 2].map(async () => { while (q.length) await loadChain(q.shift()); }));
  }
  function updateChainStatus() {
    const el = $("chain-status"); if (!el || !state.plan) return;
    const s = state.plan.places.map((p) => (state.chain.get(placeKey(p)) || {}).status);
    el.textContent = s.some((x) => x === "loading" || x === undefined) ? "Checking Monad for traveller attestations…"
      : s.some((x) => x === "err") ? "Some places could not be read from Monad right now." : "Traveller data read live from Monad.";
  }

  /* ---------- badge + feature logic ---------- */
  function badgeFor(place, ch) {
    const acc = place.access || {}, src = (acc.sources || []).length;
    const d = ch && ch.data;
    if (ch && ch.status === "loading" && !d) return { cls: "b-load", ic: "…", text: "Checking Monad…" };
    if (d && d.attesters >= 1 && d.confirmed >= 1) return { cls: "b-venue", ic: "✔", text: "Venue-confirmed" + (d.attesters > 1 ? " (" + d.attesters + " travellers)" : "") };
    if (d && d.attesters >= 2) return { cls: "b-comm", ic: "✔", text: "Community-verified (" + d.attesters + " travellers)" };
    if (d && d.attesters === 1) return { cls: "b-one", ic: "✔", text: "1 traveller verified" };
    if (src >= 2 && acc.confidence !== "low") return { cls: "b-web", ic: "!", text: "Web-sourced only" };
    return { cls: "b-none", ic: "?", text: "Unverified" };
  }
  const yn = (v) => (v === "yes" ? "yes" : v === "no" ? "no" : "unknown");

  function featList(place, ch) {
    const f = (place.access && place.access.features) || {}, d = ch && ch.data, n = d ? d.attesters : 0;
    const full = [], quiet = [];
    FEATS.forEach(([k, label], i) => {
      const web = yn(f[k]), cnt = d ? d.counts[i] || 0 : null;
      let chain;
      if (!d) chain = ch && ch.status === "err" ? "Travellers: unavailable" : "Travellers: checking…";
      else if (n === 0) chain = "Travellers: none yet";
      else chain = "Travellers: " + cnt + " of " + n + " confirmed";
      const hint = web === "yes" && d && n >= 1 && cnt === 0;
      const li = h("li", { class: "j-feat" },
        h("b", { text: label }),
        h("span", { class: "j-tags" },
          h("span", { class: "j-tag " + (web === "yes" ? "yes" : web === "no" ? "no" : "unk") }, "Web: " + web),
          h("span", { class: "j-tag chain " + (cnt > 0 ? "has" : "zero") }, chain)),
        hint ? h("p", { class: "j-gentle" }, "The web says yes, but travellers did not confirm this.") : null);
      (web === "unknown" && !cnt ? quiet : full).push(li);
    });
    const out = [h("ul", { class: "j-feats", "aria-label": "Features of " + place.name }, full)];
    if (quiet.length) out.push(h("details", { class: "j-more-f" }, h("summary", { text: "Show " + quiet.length + " features with no information yet" }), h("ul", { class: "j-feats" }, quiet)));
    return out;
  }

  /* ---------- rendering ---------- */
  const KIND = { transport: "Transport", stay: "Stay", place: "Place", food: "Food" };
  const PKIND = { airport: "Airport", station: "Station", hotel: "Hotel", attraction: "Attraction", restaurant: "Restaurant" };
  const slug = (p) => "place-" + norm(p.name + " " + p.city).replace(/ /g, "-");

  function renderPlan(plan, opts) {
    state.plan = plan;
    $("progress").hidden = true; $("error").hidden = true; $("result").hidden = false;
    const ban = $("banner");
    if (opts && opts.sample) { ban.hidden = false; ban.textContent = "Sample plan generated by the agent. Run it locally to plan your own trip."; } else ban.hidden = true;
    $("res-h").textContent = plan.title || "Your trip";
    const needs = (plan.traveler && plan.traveler.needs) || [];
    $("res-needs").textContent = (needs.length ? "Planned for: " + needs.join(", ") : "") + (plan.traveler && plan.traveler.notes ? (needs.length ? ". " : "") + plan.traveler.notes : "");
    $("res-sum").textContent = plan.summary || "";
    $("res-gen").textContent = plan.generated_at ? "Generated " + plan.generated_at : "";
    const byName = new Map((plan.places || []).map((p) => [p.name, p]));
    $("days").replaceChildren(...(plan.days || []).map((d) => h("article", { class: "j-day", "aria-labelledby": "day-" + d.day },
      h("h4", { id: "day-" + d.day }, "Day " + d.day + ": " + (d.title || "")),
      h("ol", {}, (d.items || []).map((it) => {
        const p = it.place && byName.get(it.place);
        return h("li", { class: "j-item" },
          h("span", { class: "t" }, it.time || ""),
          h("span", { class: "n" }, it.name, h("span", { class: "j-kind" }, KIND[it.kind] || it.kind || "")),
          it.city ? h("span", { class: "c" }, it.city) : null,
          it.note ? h("span", {}, it.note) : null,
          p ? h("span", {}, h("a", { class: "j-more", href: "#" + slug(p) }, "Accessibility details for " + p.name), h("span", { class: "j-mini", "data-badge": slug(p) })) : null);
      }))))) ;
    $("places").replaceChildren(...(plan.places || []).map(placeCard));
    $("tips").replaceChildren(...(plan.tips || []).map((t) => h("li", { text: t })));
    $("tips-h").hidden = $("tips").hidden = !(plan.tips || []).length;
    (plan.places || []).forEach(renderPlaceState);
    updateChainStatus();
    if (!(opts && opts.noFocus)) { $("res-h").focus({ preventScroll: true }); $("result").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion:reduce)").matches ? "auto" : "smooth", block: "start" }); }
    loadAllChain();
  }

  function placeCard(p) {
    const a = p.access || {}, id = slug(p);
    const srcs = (a.sources || []).map((s) => ({ t: s.title || s.url, u: safeUrl(s.url) })).filter((s) => s.u);
    const el = h("article", { class: "j-place", id, "aria-labelledby": id + "-h" },
      h("div", { class: "j-ph" },
        h("div", {}, h("h3", { id: id + "-h", text: p.name }), h("div", { class: "where" }, (PKIND[p.kind] || p.kind || "") + (p.city ? " in " + p.city : ""))),
        h("span", { class: "j-badge", "data-role": "badge" })),
      h("div", { class: "j-two" },
        h("div", { class: "j-panel" }, h("h4", { text: "What the web says (claimed)" }),
          h("p", { text: a.summary || "No accessibility information was found." }),
          h("p", { class: "j-hint" }, "Confidence: " + (a.confidence || "unknown") + ". " + srcs.length + (srcs.length === 1 ? " source" : " sources") + "."),
          srcs.length ? h("ul", { class: "j-src" }, srcs.map((s) => h("li", {}, h("a", { href: s.u, target: "_blank", rel: "noopener noreferrer" }, s.t, h("span", { class: "j-sr" }, " (opens in a new tab)"))))) : null),
        h("div", { class: "j-panel", "aria-live": "polite" }, h("h4", { text: "What travellers attested on Monad (verified)" }), h("p", { "data-role": "chain-line", text: "Checking Monad…" }),
          h("p", { class: "j-hint", text: "Each tick below is a real traveller's on-chain statement." }))),
      h("div", { "data-role": "feats" }),
      h("div", { class: "j-acts" },
        p.draft ? h("button", { type: "button", class: "j-btn", "aria-expanded": "false", "aria-controls": id + "-draft", "data-role": "draftbtn", onclick: (e) => toggleDraft(e.currentTarget, id) }, "Draft a message to confirm") : null,
        h("button", { type: "button", class: "j-btn", onclick: (e) => openAttest(p, e.currentTarget) }, "I have been here: confirm what is accessible"),
        h("button", { type: "button", class: "j-btn", "data-role": "retry", hidden: true, onclick: () => loadChain(p, true) }, "Retry Monad check")),
      p.draft ? h("div", { class: "j-draft", id: id + "-draft", hidden: true }, draftBody(p)) : null);
    return el;
  }

  function draftBody(p) {
    const d = p.draft, text = (d.subject ? d.subject + "\n\n" : "") + d.body;
    const wa = "https://wa.me/?text=" + encodeURIComponent(text);
    return [h("h4", { text: "Draft " + (d.channel === "whatsapp" ? "WhatsApp message" : "email") }),
      d.subject ? h("p", {}, h("strong", {}, "Subject: "), d.subject) : null, h("pre", { text: d.body }),
      h("div", { class: "j-acts" },
        h("button", { type: "button", class: "j-btn", onclick: () => copyText(text) }, "Copy message"),
        h("a", { class: "j-btn", href: wa, target: "_blank", rel: "noopener noreferrer" }, "Share on WhatsApp", h("span", { class: "j-sr" }, " (opens in a new tab)")),
        d.channel === "email" ? h("a", { class: "j-btn", href: "mailto:?subject=" + encodeURIComponent(d.subject || "") + "&body=" + encodeURIComponent(d.body) }, "Open in email app") : null)];
  }
  function toggleDraft(btn, id) {
    const box = $(id + "-draft"), open = box.hidden;
    box.hidden = !open; btn.setAttribute("aria-expanded", String(open));
    btn.textContent = open ? "Hide the draft message" : "Draft a message to confirm";
  }
  async function copyText(t) {
    try { await navigator.clipboard.writeText(t); toast("Message copied.", "ok"); return; } catch (e) { /* fall through */ }
    try { const ta = h("textarea", { "aria-hidden": "true", style: "position:fixed;left:-999px" }); ta.value = t; document.body.append(ta); ta.select(); const ok = document.execCommand("copy"); ta.remove(); toast(ok ? "Message copied." : "Could not copy. Select the text and copy it.", ok ? "ok" : "err"); } catch (e) { toast("Could not copy. Select the text and copy it.", "err"); }
  }

  function renderPlaceState(p) {
    const el = document.getElementById(slug(p)); if (!el) return;
    const ch = state.chain.get(placeKey(p)), b = badgeFor(p, ch), d = ch && ch.data;
    const badge = el.querySelector('[data-role="badge"]'); badge.className = "j-badge " + b.cls; badge.dataset.ic = b.ic; badge.textContent = b.text;
    let line;
    if (!ch || (ch.status === "loading" && !d)) line = "Checking Monad…";
    else if (ch.status === "err" && !d) line = "Could not reach Monad right now, so traveller data is unavailable. This does not mean nobody has verified it.";
    else if (d.attesters === 0) line = "No traveller has attested this place yet. Be the first.";
    else line = d.attesters + (d.attesters === 1 ? " traveller has" : " travellers have") + " attested this place on-chain; " + d.confirmed + " said the venue confirmed it in writing.";
    el.querySelector('[data-role="chain-line"]').textContent = line;
    el.querySelector('[data-role="feats"]').replaceChildren(...featList(p, ch));
    el.querySelector('[data-role="retry"]').hidden = !(ch && ch.status === "err");
    document.querySelectorAll('[data-badge="' + slug(p) + '"]').forEach((m) => { m.textContent = "· " + b.text; });
  }

  /* ---------- planning (LIVE) ---------- */
  function selectedNeeds() { return Array.from(document.querySelectorAll('input[name="need"]:checked')).map((i) => i.value); }
  const lang = () => (document.querySelector('input[name="lang"]:checked') || {}).value || "en";

  async function submitPlan(ev) {
    ev.preventDefault();
    const text = $("req").value.trim(), err = $("req-err");
    if (text.length < 8) { err.hidden = false; err.textContent = "Please describe your trip first, for example where you want to go and how many days."; $("req").focus(); return; }
    err.hidden = true;
    if (!state.live) return;
    stopSpeaking();
    $("result").hidden = true; $("error").hidden = true;
    const prog = $("progress"), list = $("stages"); list.replaceChildren(); prog.hidden = false;
    $("go").disabled = true;
    prog.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion:reduce)").matches ? "auto" : "smooth", block: "start" });
    const ac = state.abort = new AbortController();
    const addStage = (t) => { list.querySelectorAll(".cur").forEach((x) => { x.className = "done"; }); list.append(h("li", { class: "cur" }, h("span", { class: "ic", "aria-hidden": "true" }), h("span", { text: t }))); };
    let got = false;
    try {
      const res = await fetch("api/plan", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ request: text, needs: selectedNeeds(), lang: lang() }), signal: ac.signal });
      if (!res.ok || !res.body) throw new Error("The planner answered with status " + res.status + ".");
      const rd = res.body.getReader(), dec = new TextDecoder(); let buf = "";
      const handle = (line) => {
        if (!line.trim()) return; let m; try { m = JSON.parse(line); } catch (e) { return; }
        if (m.event === "stage") addStage(m.text);
        else if (m.event === "result") { got = true; renderPlan(m.data); list.querySelectorAll(".cur").forEach((x) => { x.className = "done"; }); }
        else if (m.event === "error") throw new Error(m.text || "The planner reported an error.");
      };
      for (;;) {
        const { done, value } = await rd.read(); if (done) break;
        buf += dec.decode(value, { stream: true });
        let i; while ((i = buf.indexOf("\n")) >= 0) { handle(buf.slice(0, i)); buf = buf.slice(i + 1); }
      }
      handle(buf);
      if (!got) throw new Error("The planner finished without a plan. Please try again.");
    } catch (e) {
      if (e.name === "AbortError") toast("Planning cancelled.");
      else { prog.hidden = true; $("error").hidden = false; $("error-text").textContent = e.message || String(e); }
    } finally { $("go").disabled = false; state.abort = null; }
  }

  /* ---------- voice input ---------- */
  function initMic() {
    const SR = window.SpeechRecognition || window.webkitSpeechRecognition; if (!SR) return;
    const btn = $("mic"), st = $("mic-status"); btn.hidden = false; let rec = null;
    const stop = () => { if (rec) try { rec.stop(); } catch (e) { /* ignore */ } };
    btn.addEventListener("click", () => {
      if (rec) { stop(); return; }
      rec = new SR(); rec.lang = lang() === "hi" ? "hi-IN" : "en-IN"; rec.interimResults = false; rec.continuous = false;
      rec.onstart = () => { btn.setAttribute("aria-pressed", "true"); $("mic-label").textContent = "Stop listening"; st.textContent = "Listening… speak now."; };
      rec.onresult = (e) => { let t = ""; for (let i = e.resultIndex; i < e.results.length; i++) t += e.results[i][0].transcript; t = t.trim(); if (t) { const ta = $("req"); ta.value = (ta.value.trim() ? ta.value.trim() + " " : "") + t; st.textContent = "Added: " + t; } };
      rec.onerror = (e) => { st.textContent = e.error === "not-allowed" ? "Microphone permission was denied. You can type instead." : e.error === "no-speech" ? "I did not hear anything. Try again." : "Voice input stopped (" + e.error + "). You can type instead."; };
      rec.onend = () => { rec = null; btn.setAttribute("aria-pressed", "false"); $("mic-label").textContent = "Speak your trip"; };
      try { rec.start(); } catch (e) { rec = null; st.textContent = "Could not start the microphone."; }
    });
  }

  /* ---------- read aloud ---------- */
  function stopSpeaking() {
    if (state.speaking) { try { state.speaking(); } catch (e) { /* ignore */ } state.speaking = null; }
    try { window.speechSynthesis && speechSynthesis.cancel(); } catch (e) { /* ignore */ }
    const b = $("read"); b.setAttribute("aria-pressed", "false"); $("read-label").textContent = "Read it aloud";
  }
  async function readAloud() {
    if ($("read").getAttribute("aria-pressed") === "true") { stopSpeaking(); $("read-status").textContent = "Stopped."; return; }
    const plan = state.plan; if (!plan) return;
    const text = (plan.title || "") + ". " + (plan.summary || "");
    const b = $("read"), s = $("read-status");
    b.setAttribute("aria-pressed", "true"); $("read-label").textContent = "Stop reading";
    const done = () => { if (b.getAttribute("aria-pressed") === "true") stopSpeaking(); s.textContent = "Finished reading."; };
    if (state.live && state.tts) {
      try {
        s.textContent = "Preparing audio…";
        const r = await fetch("api/tts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text }) });
        if (!r.ok) throw new Error("tts " + r.status);
        const url = URL.createObjectURL(await r.blob()), au = new Audio(url);
        state.speaking = () => { au.pause(); URL.revokeObjectURL(url); };
        au.onended = done; au.onerror = () => { stopSpeaking(); browserSpeak(text, done); };
        await au.play(); s.textContent = "Reading aloud."; return;
      } catch (e) { state.speaking = null; /* fall back */ }
    }
    browserSpeak(text, done);
  }
  function browserSpeak(text, done) {
    const s = $("read-status");
    if (!("speechSynthesis" in window)) { stopSpeaking(); s.textContent = "Your browser cannot read aloud."; return; }
    const u = new SpeechSynthesisUtterance(text); u.lang = lang() === "hi" ? "hi-IN" : "en-IN"; u.onend = done; u.onerror = done;
    $("read").setAttribute("aria-pressed", "true"); $("read-label").textContent = "Stop reading";
    s.textContent = "Reading aloud with your device voice."; speechSynthesis.cancel(); speechSynthesis.speak(u);
  }

  /* ---------- attest dialog + MetaMask ---------- */
  let dlgPlace = null, dlgOpener = null, busy = false;
  const focusables = () => Array.from($("dlg").querySelectorAll('button,input,textarea,a[href],[tabindex]:not([tabindex="-1"])')).filter((e) => !e.disabled && !e.hidden && e.offsetParent !== null);

  function openAttest(place, opener) {
    dlgPlace = place; dlgOpener = opener || document.activeElement;
    $("dlg-h").textContent = "I have been here: " + place.name;
    $("dlg-d").textContent = "Tick only what you saw yourself in " + (place.city || "this place") + ". This records your statement on Monad and costs a tiny amount of test gas.";
    $("att-feats").replaceChildren(...FEATS.map(([k, label], i) => h("label", { class: "j-check" }, h("input", { type: "checkbox", name: "af", value: String(i) }), h("span", { text: label }))));
    $("att-venue").checked = false; $("att-note").value = ""; $("att-count").textContent = "0 / 280";
    $("att-err").hidden = true; $("att-status").textContent = ""; $("att-go").disabled = false;
    $("dlg-back").hidden = false; document.body.style.overflow = "hidden";
    $("dlg").focus();
  }
  function closeAttest() {
    if (busy && !confirm("A transaction is in progress. Close this window anyway? The transaction may still complete.")) return;
    $("dlg-back").hidden = true; document.body.style.overflow = "";
    if (dlgOpener && dlgOpener.focus) dlgOpener.focus();
  }
  function dlgSay(text, ok) { const s = $("att-status"); s.replaceChildren(h("span", { class: ok ? "ok" : "" }, text)); }

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
  /* MetaMask fires accountsChanged/chainChanged during a normal connect: ignore them unless something really changed. Never reload. */
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
    ev.preventDefault(); if (busy) return;
    const ticked = Array.from($("att-feats").querySelectorAll("input:checked")).map((i) => Number(i.value));
    const e = $("att-err"); e.hidden = true;
    if (!ticked.length) { e.hidden = false; e.textContent = "Please tick at least one thing that was accessible."; return; }
    const note = $("att-note").value.trim().slice(0, 280), venue = $("att-venue").checked, place = dlgPlace;
    const mask = ticked.reduce((m, i) => m | (1 << i), 0);
    busy = true; $("att-go").disabled = true;
    try {
      const from = await ensureWallet();
      const iface = new ethers.Interface(ABI);
      const data = iface.encodeFunctionData("attest", [norm(place.name), norm(place.city), mask, venue, note]);
      dlgSay("Step 3 of 4: please confirm the transaction in your wallet…"); toast("Waiting for you to confirm in your wallet…");
      const before = (state.chain.get(placeKey(place)) || {}).data;
      const hash = await window.ethereum.request({ method: "eth_sendTransaction", params: [{ from, to: A.address, data }] });
      const link = A.explorer + "/tx/" + hash;
      dlgSay("Step 4 of 4: transaction sent. Waiting for Monad to confirm it (up to 90 seconds)…"); toast("Transaction sent. Waiting for confirmation…", "", { href: link, text: "View on Monadscan" });
      const rc = await pollReceipt(hash);
      if (!rc) { dlgSay("Sent, but we could not confirm it yet. Check the link below."); $("att-status").append(" ", h("a", { href: link, target: "_blank", rel: "noopener noreferrer" }, "View transaction")); toast("Not confirmed yet. It may still go through.", "err", { href: link, text: "View on Monadscan" }); return; }
      if (rc.status !== 1) throw new Error("The transaction failed on-chain. Nothing was recorded.");
      dlgSay("Done. Your statement is recorded on Monad. Thank you.", true);
      $("att-status").append(" ", h("a", { href: link, target: "_blank", rel: "noopener noreferrer" }, "View transaction on Monadscan", h("span", { class: "j-sr" }, " (opens in a new tab)")));
      toast("Attestation confirmed on Monad.", "ok", { href: link, text: "View on Monadscan" });
      $("att-go").hidden = true; $("att-close").textContent = "Close";
      refreshAfterAttest(place, before);
    } catch (err) {
      const m = err && (err.shortMessage || err.message) || String(err);
      const rejected = err && (err.code === 4001 || err.code === "ACTION_REJECTED" || /reject|denied/i.test(m));
      const text = rejected ? "You declined in your wallet, so nothing was sent." : /insufficient/i.test(m) ? "Your wallet does not have enough test MON to pay the network fee. Get some from the Monad testnet faucet and try again." : "Could not complete: " + m;
      dlgSay(text); toast(text, "err"); $("att-go").disabled = false;
    } finally { busy = false; }
  }
  async function refreshAfterAttest(place, before) {
    const id = placeKey(place);
    for (let i = 0; i < 6; i++) {
      await loadChain(place, true);
      const c = state.chain.get(id);
      if (c && c.data && (!before || c.data.attesters > before.attesters)) return;
      await sleep(1500);
    }
  }

  function initDialog() {
    $("att-form").addEventListener("submit", submitAttest);
    $("att-close").addEventListener("click", closeAttest);
    $("att-note").addEventListener("input", (e) => { $("att-count").textContent = e.target.value.length + " / 280"; });
    $("dlg-back").addEventListener("mousedown", (e) => { if (e.target === $("dlg-back")) closeAttest(); });
    document.addEventListener("keydown", (e) => {
      if ($("dlg-back").hidden) return;
      if (e.key === "Escape") { e.preventDefault(); closeAttest(); return; }
      if (e.key === "Tab") {
        const f = focusables(); if (!f.length) return; const first = f[0], last = f[f.length - 1], a = document.activeElement;
        if (!$("dlg").contains(a)) { e.preventDefault(); first.focus(); }
        else if (e.shiftKey && (a === first || a === $("dlg"))) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && a === last) { e.preventDefault(); first.focus(); }
      }
    });
  }

  /* ---------- sample mode / boot ---------- */
  async function loadSample() {
    for (const f of ["sample-plan.json", "dev-fixture.json"]) {
      try { const r = await fetch(f, { cache: "no-cache" }); if (r.ok) { const j = await r.json(); if (j && j.places) return j; } } catch (e) { /* next */ }
    }
    return null;
  }
  async function showSample(noFocus) {
    const p = await loadSample();
    if (!p) { toast("Could not load the sample plan.", "err"); return; }
    renderPlan(p, { sample: true, noFocus });
  }

  async function boot() {
    initPrefs(); initDialog(); watchWallet(); initMic();
    if (A) { $("addr").textContent = A.address; $("addr-link").href = A.explorer + "/address/" + A.address; }
    const ex = $("examples");
    EXAMPLES.forEach(([t, needs]) => ex.append(h("button", { type: "button", class: "j-chip-b", onclick: () => {
      $("req").value = t; document.querySelectorAll('input[name="need"]').forEach((i) => { i.checked = needs.includes(i.value); }); $("req-err").hidden = true; $("req").focus();
    } }, t)));
    $("plan-form").addEventListener("submit", submitPlan);
    $("cancel").addEventListener("click", () => { if (state.abort) state.abort.abort(); $("progress").hidden = true; });
    $("read").addEventListener("click", readAloud);
    $("sample-btn").addEventListener("click", () => showSample(false));
    try {
      const r = await withTimeout(fetch("api/config", { cache: "no-store" }), 2500, "config");
      const c = r.ok ? await r.json() : null; if (c && c.live === true) { state.live = true; state.tts = !!c.tts; }
    } catch (e) { /* sample mode */ }
    const note = $("mode-note");
    if (state.live) {
      $("sample-btn").hidden = false; document.body.dataset.mode = "live";
    } else {
      document.body.dataset.mode = "sample"; $("go").disabled = true;
      note.hidden = false; note.className = "j-note warn"; note.textContent = "Planning your own trip needs the agent running locally. This page is showing a sample plan.";
      $("req").setAttribute("aria-describedby", "req-hint req-err");
      await showSample(true);
    }
  }
  if (!window.ethers || !A) { document.addEventListener("DOMContentLoaded", () => { $("mode-note").hidden = false; $("mode-note").textContent = "This page could not load its blockchain libraries."; }); }
  else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot); else boot();
})();
