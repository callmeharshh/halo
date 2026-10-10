/* Halo Family tab: device pairing + owner wallet (MetaMask via ethers v6). Ported from docs/console.js.
   Never blocks the Companion tab: everything here degrades gracefully. */
(() => {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const H = window.Halo || { status: {}, onStatus() {}, onConn() {}, send: () => false, toast() {} };
  const G = window.GUARDVAULT || { address: "", chainId: 10143, rpc: "https://testnet-rpc.monad.xyz", explorer: "https://testnet.monadscan.com" };
  const ABI = [
    "function balanceOf(address) view returns (uint256)",
    "function policyOf(address) view returns (bool configured, bool trustedOnly, bool paused, uint128 maxPerTx, uint128 dailyLimit, address agent)",
    "function contactsOf(address) view returns (string[] names, address[] addrs)",
    "function spentInDay(address) view returns (uint256)",
    "function currentDay(address) view returns (uint256)",
    "function deposit() payable",
    "function withdraw(uint256 amount)",
    "function setPolicy(uint128 maxPerTx, uint128 dailyLimit, bool trustedOnly)",
    "function setAgent(address agent)",
    "function setPaused(bool paused)",
    "function setContact(string name, address who)",
    "function removeContact(string name)",
  ];
  const ZERO = "0x0000000000000000000000000000000000000000";
  const PAIR_BASE = "https://callmeharshh.github.io/halo/console.html?device=";
  const st = { owner: null, writable: false, signer: null, write: null, read: null, paused: false, ready: false };
  const isAddr = (a) => /^0x[0-9a-fA-F]{40}$/.test(String(a || ""));

  function msg(kind, html) { const m = $("msg"); m.dataset.kind = kind; m.innerHTML = html; }
  const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const short = (a) => a.slice(0, 6) + "…" + a.slice(-4);
  const mon = (wei) => { const s = ethers.formatEther(wei); return (s.includes(".") ? s.replace(/0+$/, "").replace(/\.$/, "") : s) + " MON"; };
  const txLink = (h) => `<a href="${G.explorer}/tx/${h}" target="_blank" rel="noopener noreferrer">${short(h)}</a>`;

  /* ---------- device card (works without ethers) ---------- */
  let lastDevice = null;
  function renderDevice(s) {
    const dev = isAddr(s.device) ? s.device : "";
    $("devAddr").textContent = dev || "waiting for the device…";
    $("devOwner").textContent = s.owner && isAddr(s.owner) ? s.owner : "not set";
    const link = dev ? PAIR_BASE + dev : "";
    $("pairLink").textContent = link || "-";
    document.querySelectorAll(".needs-copy").forEach((b) => { b.disabled = !dev; });
    const wa = $("waBtn");
    if (link) { wa.href = "https://wa.me/?text=" + encodeURIComponent("Please set up Halo for me. Open this link to approve my device and set the spending rules: " + link); wa.removeAttribute("aria-disabled"); }
    else { wa.removeAttribute("href"); wa.setAttribute("aria-disabled", "true"); }
    if (dev !== lastDevice) { lastDevice = dev; renderQr(link); }
    if (dev && !$("agAddr").value) $("agAddr").value = dev;
    if (isAddr(s.owner) && !$("lookup").value) $("lookup").value = s.owner;
    updateOneClick();
  }
  function renderQr(link) {
    const box = $("qr"), blk = $("qrBlock");
    box.textContent = "";
    try {
      if (!link || typeof window.qrcode !== "function") throw new Error("no qr");
      const q = window.qrcode(0, "M"); q.addData(link); q.make();
      box.innerHTML = q.createSvgTag({ cellSize: 4, margin: 0, scalable: true });
      blk.hidden = false;
    } catch (e) { blk.hidden = true; }
  }
  async function copyText(t) {
    try { await navigator.clipboard.writeText(t); return true; } catch (e) {
      try { const ta = document.createElement("textarea"); ta.value = t; ta.style.position = "fixed"; ta.style.opacity = "0"; document.body.appendChild(ta); ta.select(); const ok = document.execCommand("copy"); ta.remove(); return ok; } catch (e2) { return false; }
    }
  }
  document.querySelectorAll("[data-copy]").forEach((b) => b.addEventListener("click", async () => {
    const t = $(b.dataset.copy).textContent;
    const ok = await copyText(t);
    const old = b.lastChild.textContent; b.lastChild.textContent = ok ? "Copied" : "Copy failed";
    H.toast(ok ? "ok" : "warn", ok ? "Copied to clipboard" : "Could not copy. Select the text and copy it by hand.", { ms: 3000 });
    setTimeout(() => { b.lastChild.textContent = old; }, 1800);
  }));
  $("cLink").textContent = G.address; $("cLink").href = `${G.explorer}/address/${G.address}`;
  H.onStatus(renderDevice);
  H.onConn(updateOneClick);

  /* ---------- wallet ---------- */
  function updateOneClick() {
    const b = $("oneBtn"); if (!b) return;
    const ok = st.writable && isAddr(H.status.device) && H.up;
    $("oneclick").hidden = !st.writable; if ($("quick")) $("quick").hidden = !st.writable;
    b.disabled = !ok;
    b.title = ok ? "" : !H.up ? "Waiting for the device connection" : "Waiting for the device address";
  }

  async function ensureChain() {
    const hex = "0x" + Number(G.chainId).toString(16);
    try { await window.ethereum.request({ method: "wallet_switchEthereumChain", params: [{ chainId: hex }] }); }
    catch (e) {
      if (e && (e.code === 4902 || /Unrecognized chain/i.test(e.message || ""))) {
        await window.ethereum.request({ method: "wallet_addEthereumChain", params: [{ chainId: hex, chainName: "Monad Testnet", nativeCurrency: { name: "MON", symbol: "MON", decimals: 18 }, rpcUrls: (G.rpcs || [G.rpc]), blockExplorerUrls: [G.explorer] }] });
      } else throw e;
    }
  }
  async function connect() {
    if (!window.ethereum) { msg("err", "No wallet found in this browser. Install MetaMask, or paste an owner address below to view a vault read-only."); return; }
    if (!window.ethers) { msg("err", "The wallet library could not load (no internet?). The Companion still works. Try again later."); return; }
    try {
      msg("wait", "Check your wallet to connect…");
      const accounts = await window.ethereum.request({ method: "eth_requestAccounts" });
      await ensureChain();
      const provider = new ethers.BrowserProvider(window.ethereum, G.chainId);
      st.signer = await provider.getSigner();
      st.owner = ethers.getAddress(accounts[0]);
      st.write = new ethers.Contract(G.address, ABI, st.signer);
      st.writable = true;
      $("who").textContent = "Connected " + short(st.owner);
      $("connect").textContent = "Connected";
      updateOneClick();
      await refresh();
      msg("ok", "Connected. You are the owner of this vault; the device can only act inside the rules you set.");
    } catch (e) { msg("err", "Could not connect: " + esc(e.shortMessage || e.message || e)); }
  }
  async function lookup() {
    if (!window.ethers) { msg("err", "The wallet library could not load, so the vault cannot be read right now."); return; }
    const a = $("lookup").value.trim();
    if (!ethers.isAddress(a)) { msg("err", "That is not a valid address."); return; }
    st.owner = ethers.getAddress(a); st.writable = false; st.write = null;
    $("who").textContent = "Viewing " + short(st.owner) + " (read-only)";
    updateOneClick();
    try { await refresh(); msg("idle", "Read-only view. Connect the owner's wallet to change anything."); }
    catch (e) { msg("err", "Could not read the vault: " + esc(e.shortMessage || e.message || e)); }
  }
  async function refresh() {
    if (!st.owner) return;
    const o = st.owner;
    // Public RPCs sometimes return empty eth_call results under load: rotate endpoints and retry, no batching.
    const urls = G.rpcs || [G.rpc];
    st.rpcIdx = st.rpcIdx || 0;
    let res, lastErr;
    for (let i = 0; i < urls.length * 2 && !res; i++) {
      try {
        const prov = new ethers.JsonRpcProvider(urls[(st.rpcIdx + i) % urls.length], G.chainId, { staticNetwork: true, batchMaxCount: 1 });
        const c = new ethers.Contract(G.address, ABI, prov);
        res = await Promise.all([c.balanceOf(o), c.policyOf(o), c.contactsOf(o), c.spentInDay(o), c.currentDay(o)]);
        st.rpcIdx = (st.rpcIdx + i) % urls.length; st.read = c;
      } catch (e) { lastErr = e; await new Promise((r) => setTimeout(r, 200 * (i + 1))); }
    }
    if (!res) throw lastErr || new Error("network read failed");
    const [bal, pol, book, spent, day] = res;
    const today = BigInt(Math.floor(Date.now() / 1000 / 86400));
    const spentToday = day === today ? spent : 0n;
    st.paused = pol.paused;
    $("dash").hidden = false; $("actions").hidden = !st.writable;
    $("vOwner").textContent = o; $("vBal").textContent = mon(bal);
    $("vSpent").textContent = pol.configured ? `${mon(spentToday)} of ${mon(pol.dailyLimit)}` : mon(spentToday);
    const ok = pol.configured && pol.agent !== ZERO;
    $("vStatus").innerHTML = !pol.configured ? '<span class="tag warn">Rules not set</span>' : pol.paused ? '<span class="tag err">Paused</span>' : ok ? '<span class="tag ok">Active</span>' : '<span class="tag warn">No device approved</span>';
    $("vAgent").textContent = pol.agent === ZERO ? "none" : pol.agent;
    $("pMax").textContent = pol.configured ? mon(pol.maxPerTx) : "not set";
    $("pDay").textContent = pol.configured ? mon(pol.dailyLimit) : "not set";
    $("pTrust").textContent = !pol.configured ? "not set" : pol.trustedOnly ? "Trusted contacts only" : "Anyone";
    $("pauseBtn").textContent = pol.paused ? "Resume payments" : "Pause payments";
    const body = $("cBody"); body.textContent = "";
    $("cEmpty").hidden = book.names.length > 0;
    book.names.forEach((n, i) => {
      const tr = document.createElement("tr");
      const tn = document.createElement("td"); tn.textContent = n;
      const ta = document.createElement("td"); ta.className = "mono"; ta.textContent = short(book.addrs[i]); ta.title = book.addrs[i];
      const tb = document.createElement("td");
      if (st.writable) {
        const b = document.createElement("button"); b.className = "btn mini"; b.type = "button"; b.textContent = "Remove";
        b.setAttribute("aria-label", "Remove contact " + n);
        b.addEventListener("click", () => act("Removing " + n, () => st.write.removeContact(n)));
        tb.appendChild(b);
      }
      tr.append(tn, ta, tb); body.appendChild(tr);
    });
    if (st.writable && pol.configured) {
      $("polMax").placeholder = ethers.formatEther(pol.maxPerTx); $("polDay").placeholder = ethers.formatEther(pol.dailyLimit); $("polTrust").checked = pol.trustedOnly;
    }
  }

  /* Confirm a transaction through OUR reliable RPCs. MetaMask's own RPC can hang or lag, so tx.wait() is not trusted. */
  async function waitReceipt(hash, timeoutMs) {
    const urls = G.rpcs || [G.rpc]; const t0 = Date.now(); let i = 0;
    while (Date.now() - t0 < (timeoutMs || 90000)) {
      try {
        const prov = new ethers.JsonRpcProvider(urls[i % urls.length], G.chainId, { staticNetwork: true, batchMaxCount: 1 });
        const r = await prov.getTransactionReceipt(hash);
        if (r) return r;
      } catch (e) { i++; }
      await new Promise((res) => setTimeout(res, 1200));
    }
    return null;
  }
  async function act(label, send, quiet) {
    if (!st.writable) { msg("err", "Connect the owner's wallet first."); return false; }
    try {
      msg("wait", esc(label) + "… confirm in your wallet.");
      const tx = await send();
      msg("wait", esc(label) + "… sent " + txLink(tx.hash) + ", waiting for Monad to confirm.");
      const r = await waitReceipt(tx.hash, 90000);
      if (r && r.status !== 1) throw new Error("transaction failed on-chain");
      if (!r) msg("wait", esc(label) + ": sent " + txLink(tx.hash) + ". Monad is slow to confirm; it should land shortly (check the explorer).");
      try { await refresh(); } catch (e) { /* balances refresh on the next poll */ }
      if (!quiet) msg("ok", esc(label) + " done. " + txLink(tx.hash));
      return tx.hash;
    } catch (e) {
      const rej = e && (e.code === "ACTION_REJECTED" || e.code === 4001);
      msg("err", rej ? "You rejected the request in your wallet. Nothing changed." : esc(label) + " failed: " + esc(e.reason || e.shortMessage || e.message || e));
      return false;
    }
  }
  function amount(id, what) {
    const v = $(id).value.trim();
    if (!/^\d*\.?\d+$/.test(v) || Number(v) <= 0) { msg("err", `Enter a ${what} greater than zero.`); return null; }
    return ethers.parseEther(v);
  }

  /* One click: approve the device on-chain, then tell the device who owns it. */
  let busy = false;
  async function oneClick() {
    if (busy) return;
    const dev = H.status.device;
    if (!st.writable || !isAddr(dev)) { msg("err", "Connect MetaMask first, and wait for the device address to appear."); return; }
    busy = true; $("oneBtn").disabled = true;
    try {
      const addr = st.owner;
      H.toast("info", "Step 1 of 2: approve the device", { sub: "Confirm in MetaMask, then wait a few seconds." });
      const hash = await act("Step 1 of 2: approving this device", () => st.write.setAgent(ethers.getAddress(dev)), true);
      if (!hash) return;
      H.toast("info", "Step 2 of 2: linking this device to your wallet");
      msg("wait", "Step 2 of 2: telling this device you are its owner…");
      if (!H.send({ type: "set_owner", address: addr })) { msg("err", "Device approved, but the device connection dropped. Press the button again once it reconnects."); return; }
      const ok = await waitOwner(addr, 6000);
      msg("ok", (ok ? "All set. " : "Approved and sent. ") + `${short(addr)} now owns this device and it is approved ${txLink(hash)}.`);
      H.toast("ok", "This wallet now owns the device", { sub: "The device can spend only inside your rules." });
    } finally { busy = false; updateOneClick(); }
  }
  /* Quick setup: fund the vault, set safe limits, add Alice. Visible checklist; each step is one MetaMask confirmation. */
  let quickBusy = false;
  async function quickSetup() {
    if (quickBusy) return;
    if (!st.writable) { msg("err", "Connect MetaMask first."); return; }
    const D = window.HALO_QUICK_DEFAULTS || { deposit: "0.3", max: "0.1", day: "0.3" };
    const mark = (k, cls) => { const li = document.querySelector(`#quickSteps li[data-s="${k}"]`); if (li) li.className = cls; };
    quickBusy = true; $("quickBtn").disabled = true;
    ["fund", "rules", "contact"].forEach((k) => mark(k, ""));
    try {
      mark("fund", "doing");
      let have = 0n; try { have = await st.read.balanceOf(st.owner); } catch (e) { /* treat as empty */ }
      const want = ethers.parseEther(D.deposit);
      if (have < want) {
        const ok = await act("Funding the vault", () => st.write.deposit({ value: want - have }), true);
        if (!ok) { mark("fund", "err"); return; }
      }
      mark("fund", "done");
      mark("rules", "doing");
      const ok2 = await act("Setting safe limits", () => st.write.setPolicy(ethers.parseEther(D.max), ethers.parseEther(D.day), true), true);
      if (!ok2) { mark("rules", "err"); return; }
      mark("rules", "done");
      mark("contact", "doing");
      const typed = $("ctAddr") ? $("ctAddr").value.trim() : "";
      const alice = ethers.isAddress(typed) ? ethers.getAddress(typed) : ethers.getAddress(st.owner);
      const ok3 = await act("Adding Alice", () => st.write.setContact("alice", alice), true);
      if (!ok3) { mark("contact", "err"); return; }
      mark("contact", "done");
      msg("ok", "All set. Now say: \"Send 0.05 MON to Alice\".");
      H.toast("ok", "Setup complete", { sub: 'Try: "Send 0.05 MON to Alice"' });
      H.send({ type: "refresh" });
    } finally { quickBusy = false; $("quickBtn").disabled = false; }
  }

  function waitOwner(addr, ms) {
    return new Promise((res) => {
      const t0 = Date.now();
      const iv = setInterval(() => {
        const o = String(H.status.owner || "").toLowerCase();
        if (o === addr.toLowerCase()) { clearInterval(iv); res(true); }
        else if (Date.now() - t0 > ms) { clearInterval(iv); res(false); }
      }, 150);
    });
  }

  function wire() {
    st.ready = true;
    $("connect").addEventListener("click", connect);
    $("oneBtn").addEventListener("click", oneClick);
    if ($("quickBtn")) $("quickBtn").addEventListener("click", quickSetup);
    $("lookupBtn").addEventListener("click", lookup);
    $("lookup").addEventListener("keydown", (e) => { if (e.key === "Enter") lookup(); });
    $("fDeposit").addEventListener("submit", (e) => { e.preventDefault(); const v = amount("depAmt", "amount"); if (v) act("Depositing", () => st.write.deposit({ value: v })); });
    $("withdrawAll").addEventListener("click", async () => { try { const b = await st.read.balanceOf(st.owner); if (b === 0n) { msg("err", "The vault is empty."); return; } act("Withdrawing everything", () => st.write.withdraw(b)); } catch (e) { msg("err", "Could not read the balance."); } });
    $("fPolicy").addEventListener("submit", (e) => {
      e.preventDefault();
      const m = amount("polMax", "per-payment limit"), d = amount("polDay", "daily limit");
      if (!m || !d) return;
      if (m > d) { msg("err", "The per-payment limit cannot be higher than the daily limit."); return; }
      act("Saving rules", () => st.write.setPolicy(m, d, $("polTrust").checked));
    });
    $("fAgent").addEventListener("submit", (e) => {
      e.preventDefault(); const a = $("agAddr").value.trim();
      if (!ethers.isAddress(a)) { msg("err", "That device address is not valid."); return; }
      act("Approving device", () => st.write.setAgent(ethers.getAddress(a)));
    });
    $("pauseBtn").addEventListener("click", () => act(st.paused ? "Resuming payments" : "Pausing payments", () => st.write.setPaused(!st.paused)));
    $("revokeBtn").addEventListener("click", () => act("Revoking device", () => st.write.setAgent(ZERO)));
    $("fContact").addEventListener("submit", (e) => {
      e.preventDefault();
      const n = $("ctName").value.trim().toLowerCase(), a = $("ctAddr").value.trim();
      if (!/^[a-z0-9 ]{1,32}$/.test(n)) { msg("err", "Names can only use letters, numbers and spaces (max 32)."); return; }
      if (!ethers.isAddress(a)) { msg("err", "That wallet address is not valid."); return; }
      act("Saving " + n, () => st.write.setContact(n, ethers.getAddress(a)));
      $("ctName").value = ""; $("ctAddr").value = "";
    });
    if (window.ethereum && window.ethereum.on) {
      const reset = () => { st.writable = false; st.write = null; st.signer = null; $("who").textContent = "Wallet changed. Connect again."; $("connect").textContent = "Connect MetaMask"; $("actions").hidden = true; updateOneClick(); };
      // MetaMask fires both events during a NORMAL connect (permission grant, then switch to Monad). Ignore those; reset only on a real change.
      window.ethereum.on("accountsChanged", (a) => {
        if (!st.writable) return;
        if (a && a[0] && st.owner && a[0].toLowerCase() === st.owner.toLowerCase()) return;
        reset();
      });
      window.ethereum.on("chainChanged", (c) => {
        if (parseInt(c, 16) === G.chainId) return;
        if (st.writable) reset();
      });
    }
    updateOneClick();
  }

  let tries = 0;
  (function boot() {
    if (window.ethers) return wire();
    if (++tries > 200) { msg("err", "The wallet library could not load (no internet?). The Companion still works; Family tools need the internet."); $("connect").disabled = true; return; }
    setTimeout(boot, 50);
  })();
})();
