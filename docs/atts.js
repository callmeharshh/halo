/* Live feed of AccessRegistry attestations (real travellers, on Monad). Snapshot (atts.json) + live scan of newer blocks. */
(function () {
  const R = window.ACCESSREG; if (!R) return;
  const $ = (id) => document.getElementById(id);
  const NAMES = ["Step-free entrance", "Ramp", "Lift", "Accessible restroom", "Accessible room/seating", "Tactile / braille", "Hearing loop / sign", "Quiet space", "Assistance", "Accessible parking"];
  const ABI = ["event Attested(bytes32 indexed place, string placeName, string city, address indexed by, uint16 features, bool venueConfirmed, string note, uint256 timestamp)", "function totalAttestations() view returns (uint256)"];
  const state = { rows: new Map(), last: null, idx: 0 };
  const short = (a) => a.slice(0, 6) + "…" + a.slice(-4);
  const hex = (n) => "0x" + n.toString(16);
  const ago = (ts) => { const d = Math.max(0, Math.floor(Date.now() / 1000) - ts); return d < 60 ? d + "s ago" : d < 3600 ? Math.floor(d / 60) + "m ago" : d < 86400 ? Math.floor(d / 3600) + "h ago" : Math.floor(d / 86400) + "d ago"; };
  const title = (s) => s.replace(/\b[a-z]/g, (c) => c.toUpperCase());

  async function rpc(method, params) {
    const urls = R.rpcs || [R.rpc]; let last;
    for (let i = 0; i < urls.length * 2; i++) {
      const ctl = new AbortController(); const t = setTimeout(() => ctl.abort(), 10000);
      try {
        const r = await fetch(urls[(state.idx + i) % urls.length], { method: "POST", headers: { "content-type": "application/json" }, signal: ctl.signal, body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }) });
        const j = await r.json(); if (j.error) throw new Error(j.error.message);
        if (j.result === undefined || j.result === null) throw new Error("empty");
        state.idx = (state.idx + i) % urls.length; return j.result;
      } catch (e) { last = e; await new Promise((res) => setTimeout(res, 150 * (i + 1))); } finally { clearTimeout(t); }
    }
    throw last;
  }
  function render() {
    const rows = [...state.rows.values()].sort((a, b) => b.block - a.block || b.ts - a.ts).slice(0, 30);
    $("att-count").textContent = state.rows.size; $("att-places").textContent = new Set([...state.rows.values()].map((r) => r.place + "|" + r.city)).size;
    $("att-table").hidden = rows.length === 0; const body = $("att-body"); body.textContent = "";
    for (const r of rows) {
      const tr = document.createElement("tr"); const td = (t, l) => { const c = document.createElement("td"); c.dataset.label = l; c.textContent = t; tr.appendChild(c); return c; };
      td(ago(r.ts), "Time"); td(title(r.place) + (r.city ? ", " + title(r.city) : ""), "Place");
      const feats = NAMES.filter((_, i) => r.features & (1 << i)); td(feats.length ? feats.join(", ") : "none ticked", "Confirmed");
      td(r.venueConfirmed ? "Venue confirmed" : "Traveller", "By"); td(short(r.by), "Wallet").title = r.by;
      const c = td("", "Tx"); const a = document.createElement("a"); a.href = R.explorer + "/tx/" + r.tx; a.target = "_blank"; a.rel = "noopener noreferrer"; a.textContent = short(r.tx); c.appendChild(a); body.appendChild(tr);
    }
    $("att-status").textContent = rows.length ? "Live. Updated " + new Date().toLocaleTimeString() + ", refreshing every 8s." : "No attestations yet. Be the first: open a plan and confirm a place.";
  }
  async function scan(from, to) {
    const iface = new ethers.Interface(ABI), topic = iface.getEvent("Attested").topicHash;
    const chunks = []; for (let hi = to; hi >= from; hi -= 100) chunks.push([Math.max(from, hi - 99), hi]);
    let i = 0;
    async function worker() { while (i < chunks.length) { const [a, b] = chunks[i++]; const logs = await rpc("eth_getLogs", [{ address: R.address, fromBlock: hex(a), toBlock: hex(b), topics: [topic] }]);
      for (const l of logs) { const p = iface.parseLog(l); state.rows.set(l.transactionHash + ":" + l.logIndex, { tx: l.transactionHash, block: parseInt(l.blockNumber, 16), place: p.args.placeName, city: p.args.city, by: p.args.by, features: Number(p.args.features), venueConfirmed: p.args.venueConfirmed, ts: Number(p.args.timestamp) }); } if (logs.length) render(); } }
    await Promise.all(Array.from({ length: Math.min(6, chunks.length) }, worker));
  }
  async function snapshot() { try { const r = await fetch("atts.json?ts=" + Date.now(), { cache: "no-store" }); if (!r.ok) return null; const j = await r.json(); if ((j.address || "").toLowerCase() !== R.address.toLowerCase()) return null; for (const x of j.rows) state.rows.set(x.key, x); render(); return j.lastBlock; } catch (e) { return null; } }
  async function tick(first) {
    try { const head = parseInt(await rpc("eth_blockNumber", []), 16); const from = first ? Math.max(R.deployBlock, (state.last || 0) + 1) : state.last + 1; if (head >= from) await scan(from, head); state.last = head; render(); }
    catch (e) { $("att-status").textContent = "Reconnecting to Monad…"; }
    setTimeout(() => tick(false), 8000);
  }
  window.addEventListener("DOMContentLoaded", () => { const a = $("reg-addr"); if (a) { a.textContent = R.address; $("reg-scan").href = R.explorer + "/address/" + R.address; $("reg-vis").href = R.vision + "/address/" + R.address; } });
  window.addEventListener("DOMContentLoaded", () => { const boot = async () => { if (!window.ethers || !$("att-body")) return window.ethers ? null : setTimeout(boot, 60); state.last = await snapshot(); tick(true); }; boot(); });
})();
