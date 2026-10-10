/* Halo companion UI. Talks to the Python backend over WebSocket /ws. Plain JS, no build step. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const safeUrl = (u) => (/^https?:\/\//i.test(String(u || "")) ? String(u) : "");
  const H = (window.Halo = { status: {}, up: false, listeners: [], connListeners: [] });
  H.onStatus = (fn) => { H.listeners.push(fn); fn(H.status); };
  H.onConn = (fn) => { H.connListeners.push(fn); fn(H.up); };

  /* ---------- tabs ---------- */
  const tabs = [$("tab-companion"), $("tab-family")];
  function showTab(name) {
    tabs.forEach((t) => { const on = t.id === "tab-" + name; t.setAttribute("aria-selected", on); t.tabIndex = on ? 0 : -1; $("view-" + t.id.slice(4)).hidden = !on; });
    try { localStorage.setItem("halo-tab", name); } catch (e) { /* storage unavailable */ }
  }
  H.showTab = showTab;
  tabs.forEach((t, i) => {
    t.addEventListener("click", () => showTab(t.id.slice(4)));
    t.addEventListener("keydown", (e) => {
      if (e.key === "ArrowRight" || e.key === "ArrowLeft") { const n = tabs[(i + 1) % 2]; n.focus(); showTab(n.id.slice(4)); e.preventDefault(); }
    });
  });
  if (location.hash === "#family") showTab("family");

  /* ---------- toasts ---------- */
  function toast(level, text, opts = {}) {
    const el = document.createElement("div");
    el.className = "toast " + (level || "info");
    const body = document.createElement("div");
    const p = document.createElement("p"); p.textContent = text; body.appendChild(p);
    if (opts.sub) { const s = document.createElement("p"); s.className = "sub"; s.textContent = opts.sub; body.appendChild(s); }
    if (safeUrl(opts.link)) { const a = document.createElement("a"); a.href = opts.link; a.target = "_blank"; a.rel = "noopener noreferrer"; a.textContent = opts.linkText || "View on explorer"; body.appendChild(a); }
    const x = document.createElement("button"); x.className = "x"; x.type = "button"; x.setAttribute("aria-label", "Dismiss message"); x.textContent = "×";
    x.addEventListener("click", () => el.remove());
    el.append(body, x);
    const box = $("toasts"); box.appendChild(el);
    while (box.children.length > 4) box.firstChild.remove();
    setTimeout(() => el.remove(), opts.ms || (level === "err" ? 12000 : 9000));
  }
  H.toast = toast;

  /* ---------- websocket ---------- */
  let ws = null, retry = 0, timer = null;
  function setConn(up, text) {
    H.up = up;
    $("conn").dataset.state = up ? "up" : "down";
    $("connText").textContent = text || (up ? "Connected" : "Reconnecting…");
    document.querySelectorAll(".needs-ws").forEach((b) => { b.disabled = !up; });
    H.connListeners.forEach((f) => f(up));
  }
  function send(obj) {
    if (!ws || ws.readyState !== 1) { toast("warn", "Not connected yet. Please wait a moment."); return false; }
    ws.send(JSON.stringify(obj)); return true;
  }
  H.send = send;
  function connect() {
    clearTimeout(timer);
    try { ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws"); }
    catch (e) { schedule(); return; }
    ws.onopen = () => { retry = 0; setConn(true); send({ type: "refresh" }); };
    ws.onmessage = (ev) => { let m; try { m = JSON.parse(ev.data); } catch (e) { return; } try { handle(m); } catch (e) { console.warn("handler", e); } };
    ws.onclose = () => { setConn(false); hideConfirm(); schedule(); };
    ws.onerror = () => { try { ws.close(); } catch (e) { /* ignore */ } };
  }
  function schedule() { retry++; timer = setTimeout(connect, Math.min(8000, 400 * 2 ** Math.min(retry, 5))); }

  function handle(m) {
    if (!m || typeof m !== "object") return;
    switch (m.type) {
      case "state": setOrb(m.value); break;
      case "event": onEvent(m); break;
      case "confirm": m.pending ? showConfirm(m) : hideConfirm(); break;
      case "status": onStatus(m.data || {}); break;
      case "toast": toast(m.level, m.text); break;
    }
  }

  /* ---------- orb ---------- */
  const LABELS = { listening: "Listening", hearing: "I hear you", thinking: "Thinking", speaking: "Speaking" };
  let orbState = "idle";
  function setOrb(v) {
    orbState = LABELS[v] ? v : "idle";
    $("orb").dataset.state = orbState;
    renderState();
  }
  function renderState() {
    $("stateLabel").textContent = LABELS[orbState] || (H.status.listening ? "Ready, say something" : "Tap to start");
  }

  /* ---------- events, captions, history, timeline ---------- */
  let lastApproved = "";
  const hist = [];
  function addHist(who, text) {
    hist.push({ who, text }); while (hist.length > 6) hist.shift();
    const ol = $("histList"); ol.textContent = "";
    hist.forEach((h) => {
      const li = document.createElement("li"); li.className = h.who === "You" ? "u" : "h";
      const b = document.createElement("b"); b.textContent = h.who;
      li.append(b, document.createTextNode(h.text)); ol.appendChild(li);
    });
    ol.scrollTop = ol.scrollHeight;
  }
  const KIND = { say: "heard", route: "routing", tool: "tool", reply: "reply", ask: "asking", approved: "approved", denied: "denied", timeout: "timed out", tx: "payment sent", review: "review", send: "sending", error: "problem" };
  function onEvent(m) {
    const text = String(m.text == null ? "" : m.text), kind = m.kind || "", agent = m.agent || "System";
    if (kind === "say") { const u = $("userText"); u.textContent = text; u.classList.remove("placeholder"); addHist("You", text); }
    if (kind === "reply") { $("haloText").textContent = text; addHist("Halo", text); }
    if (kind === "approved") lastApproved = text;
    if (kind === "tx") {
      const how = (lastApproved || "").replace(/^via\s+/i, "");
      toast("ok", "Payment sent", { sub: how ? "Approved by " + how : "", link: text, linkText: "View on explorer", ms: 14000 });
      lastApproved = "";
    }
    if (kind === "error") toast("err", text);
    addTimeline(agent, kind, text);
  }
  function addTimeline(agent, kind, text) {
    const tl = $("timeline");
    const empty = tl.querySelector(".empty"); if (empty) empty.remove();
    const li = document.createElement("li");
    const safeAgent = /^[A-Za-z]+$/.test(agent) ? agent : "System";
    li.className = "ag-" + safeAgent + " k-" + kind;
    const meta = document.createElement("div"); meta.className = "meta";
    const chip = document.createElement("span"); chip.className = "achip"; chip.textContent = safeAgent;
    const k = document.createElement("span"); k.textContent = (KIND[kind] || kind) + " · " + new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    meta.append(chip, k);
    const body = document.createElement("div");
    if (kind === "tx" && safeUrl(text)) { const a = document.createElement("a"); a.href = text; a.target = "_blank"; a.rel = "noopener noreferrer"; a.textContent = "View transaction on explorer"; body.appendChild(a); }
    else body.textContent = text;
    li.append(meta, body); tl.appendChild(li);
    while (tl.children.length > 100) tl.firstChild.remove();
    tl.scrollTop = tl.scrollHeight;
  }
  $("agentsBtn").addEventListener("click", () => {
    const b = $("agentsBtn"), open = b.getAttribute("aria-expanded") !== "true";
    b.setAttribute("aria-expanded", open); $("timeline").hidden = !open;
  });

  /* ---------- status ---------- */
  function setChip(id, cls) { const c = $(id); c.classList.remove("warn", "err", "good"); if (cls) c.classList.add(cls); }
  let bannerDismissed = false;
  function onStatus(d) {
    H.status = d || {};
    const p = d.policy || {};
    $("vaultVal").textContent = d.vault != null && d.vault !== "" ? d.vault + " MON" : "-";
    const hasPol = d.policy && p.configured;
    $("limitsVal").textContent = hasPol ? `${p.max_per_tx} per payment, ${p.daily_limit} per day, ${p.trusted_only ? "contacts only" : "anyone"}` : (d.policy ? "not set" : "-");
    $("llmVal").textContent = d.llm || "-";
    $("modeVal").textContent = d.mode === "solo" ? "Solo vault" : d.mode === "family" ? "Family-managed" : "-";
    const g = $("chipGuard"); const ex = safeUrl(d.explorer) || (window.GUARDVAULT && window.GUARDVAULT.explorer) || "";
    const addr = d.contract || (window.GUARDVAULT && window.GUARDVAULT.address) || "";
    if (ex && addr) g.href = ex.replace(/\/$/, "") + "/address/" + addr; else g.removeAttribute("href");
    let guard = "Protected by GuardVault", gcls = "good", lcls = "";
    if (d.policy) {
      if (p.paused) { guard = "Payments paused"; gcls = "err"; lcls = "err"; }
      else if (!p.configured) { guard = "Rules not set"; gcls = "warn"; lcls = "warn"; }
      else if (!p.agent_ok) { guard = "Device not approved"; gcls = "warn"; }
    }
    $("guardVal").textContent = guard; setChip("chipGuard", gcls); setChip("chipLimits", lcls);
    setChip("chipVault", p.paused ? "err" : "");
    // controls
    const on = !!d.listening;
    $("micBtn").setAttribute("aria-pressed", on); $("micState").textContent = on ? "ON" : "OFF";
    const tr = d.assistant_mode === "transcribe";
    $("modeA").setAttribute("aria-checked", !tr); $("modeD").setAttribute("aria-checked", tr);
    const gz = d.gaze || {}; $("gazeBtn").setAttribute("aria-checked", !!gz.on); $("gazeState").textContent = gz.on ? "on" : "off";
    $("calBtn").textContent = gz.calibrated ? "Recalibrate eyes" : "Calibrate eyes";
    renderState();
    // setup banner
    const need = d.policy && (!p.configured || !p.agent_ok);
    $("setupBanner").hidden = !(need && !bannerDismissed);
    H.listeners.forEach((f) => { try { f(H.status); } catch (e) { console.warn(e); } });
  }
  $("bannerGo").addEventListener("click", () => { showTab("family"); window.scrollTo(0, 0); });
  $("bannerX").addEventListener("click", () => { bannerDismissed = true; $("setupBanner").hidden = true; });

  /* ---------- controls ---------- */
  const toggleMic = () => { if (!H.up) return; const on = !H.status.listening; H.status.listening = on; send({ type: "mic", on }); onStatus(H.status); };
  $("micBtn").addEventListener("click", toggleMic);
  $("orb").addEventListener("click", toggleMic);
  $("scamBtn").addEventListener("click", () => send({ type: "scam" }));
  document.querySelectorAll(".seg button").forEach((b) => b.addEventListener("click", () => send({ type: "mode", value: b.dataset.v })));
  $("gazeBtn").addEventListener("click", () => send({ type: "gaze", on: $("gazeBtn").getAttribute("aria-checked") !== "true" }));
  $("calBtn").addEventListener("click", () => send({ type: "calibrate" }));
  $("typeForm").addEventListener("submit", (e) => {
    e.preventDefault(); const i = $("typeIn"), t = i.value.trim();
    if (t && send({ type: "say", text: t })) i.value = "";
  });

  /* ---------- confirmation ---------- */
  let cfTimer = null, cfEnd = 0, cfTotal = 25, cfOpener = null;
  const CIRC = 339.3;
  function showConfirm(m) {
    cfTotal = Number(m.timeout) > 0 ? Number(m.timeout) : 25;
    const amt = m.amount != null && m.amount !== "" ? String(m.amount) : "";
    $("cfAmt").textContent = amt ? amt + " MON" : "Payment";
    $("cfTo").textContent = m.to || "this contact"; $("cfAddr").textContent = m.address || "";
    if (!amt && m.text) $("cfAmt").textContent = String(m.text);
    const n = $("cfNote"); n.hidden = !m.note; n.textContent = m.note || "";
    if ($("confirmOv").hidden) cfOpener = document.activeElement;
    $("confirmOv").hidden = false;
    clearInterval(cfTimer); cfEnd = Date.now() + cfTotal * 1000;
    const tick = () => {
      const left = Math.max(0, (cfEnd - Date.now()) / 1000);
      $("cfSecs").textContent = Math.ceil(left);
      $("cfRing").style.strokeDashoffset = String(CIRC * (1 - left / cfTotal));
      if (left <= -3) hideConfirm(); // server normally hides it; fallback if the message is lost
    };
    tick(); cfTimer = setInterval(tick, 200);
    $("cfNo").focus(); // safest default: Enter never approves a payment by accident
  }
  function hideConfirm() {
    clearInterval(cfTimer);
    if ($("confirmOv").hidden) return;
    $("confirmOv").hidden = true;
    if (cfOpener && cfOpener.focus) { try { cfOpener.focus(); } catch (e) { /* gone */ } }
  }
  const decide = (v) => { send({ type: "confirm", decision: v }); };
  $("cfYes").addEventListener("click", () => decide(true));
  $("cfNo").addEventListener("click", () => decide(false));

  /* ---------- keyboard ---------- */
  document.addEventListener("keydown", (e) => {
    if (!$("confirmOv").hidden) {
      if (e.key === "Tab") {
        const f = [$("cfYes"), $("cfNo")], i = f.indexOf(document.activeElement);
        const next = e.shiftKey ? f[(i <= 0 ? f.length : i) - 1] : f[(i + 1) % f.length];
        next.focus(); e.preventDefault();
      }
      return; // Esc does not dismiss a payment prompt
    }
    if (e.key === "Escape") { $("toasts").textContent = ""; if (!$("setupBanner").hidden) $("bannerX").click(); return; }
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const t = e.target, tag = t && t.tagName;
    if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || (t && t.isContentEditable)) return;
    const comp = !$("view-companion").hidden;
    if (comp && (e.key.toLowerCase() === "m" || (e.key === " " && tag !== "BUTTON" && tag !== "A" && tag !== "SUMMARY"))) { e.preventDefault(); toggleMic(); }
  });

  setConn(false, "Connecting…");
  connect();
})();
