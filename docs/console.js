/* Halo Family Console. Plain JS + ethers v6. Talks directly to the GuardVault contract (docs/contract.js). */
const G = window.GUARDVAULT;
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
const $ = (id) => document.getElementById(id);
const st = { owner: null, writable: false, signer: null, write: null, read: null, paused: false };

function msg(kind, html) { const m = $("msg"); m.dataset.kind = kind; m.innerHTML = html; }
const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const short = (a) => a.slice(0, 6) + "…" + a.slice(-4);
const mon = (wei) => { const s = ethers.formatEther(wei); return (s.includes(".") ? s.replace(/0+$/, "").replace(/\.$/, "") : s) + " MON"; };
const txLink = (h) => `<a href="${G.explorer}/tx/${h}" target="_blank" rel="noopener noreferrer">${short(h)}</a>`;

async function ensureChain() {
  const hex = "0x" + G.chainId.toString(16);
  try {
    await window.ethereum.request({ method: "wallet_switchEthereumChain", params: [{ chainId: hex }] });
  } catch (e) {
    if (e && (e.code === 4902 || /Unrecognized chain/i.test(e.message || ""))) {
      await window.ethereum.request({ method: "wallet_addEthereumChain", params: [{
        chainId: hex, chainName: "Monad Testnet", nativeCurrency: { name: "MON", symbol: "MON", decimals: 18 },
        rpcUrls: [G.rpc], blockExplorerUrls: [G.explorer] }] });
    } else throw e;
  }
}

async function connect() {
  if (!window.ethereum) { msg("err", "No wallet found in this browser. Install MetaMask, or paste an address above to view a vault read-only."); return; }
  try {
    msg("wait", "Check your wallet to connect…");
    const accounts = await window.ethereum.request({ method: "eth_requestAccounts" });
    await ensureChain();
    const provider = new ethers.BrowserProvider(window.ethereum);
    st.signer = await provider.getSigner();
    st.owner = ethers.getAddress(accounts[0]);
    st.write = new ethers.Contract(G.address, ABI, st.signer);
    st.writable = true;
    $("who").textContent = "Connected " + short(st.owner);
    $("connect").textContent = "Connected";
    await refresh();
    msg("ok", "Connected. You are the owner of this vault; the assistant's device can only act inside the rules you set.");
  } catch (e) { msg("err", "Could not connect: " + esc(e.shortMessage || e.message || e)); }
}

async function lookup() {
  const a = $("lookup").value.trim();
  if (!ethers.isAddress(a)) { msg("err", "That is not a valid address."); return; }
  st.owner = ethers.getAddress(a); st.writable = false; st.write = null;
  $("who").textContent = "Viewing " + short(st.owner) + " (read-only)";
  await refresh();
  msg("idle", "Read-only view. Connect the owner's wallet to change anything.");
}

async function refresh() {
  if (!st.owner) return;
  st.read = st.read || new ethers.Contract(G.address, ABI, new ethers.JsonRpcProvider(G.rpc));
  const o = st.owner;
  const [bal, pol, book, spent, day] = await Promise.all([
    st.read.balanceOf(o), st.read.policyOf(o), st.read.contactsOf(o), st.read.spentInDay(o), st.read.currentDay(o)]);
  const today = BigInt(Math.floor(Date.now() / 1000 / 86400));
  const spentToday = day === today ? spent : 0n;
  st.paused = pol.paused;
  $("dash").hidden = false;
  $("actions").hidden = !st.writable;
  $("vOwner").textContent = o;
  $("vBal").textContent = mon(bal);
  $("vSpent").textContent = pol.configured ? `${mon(spentToday)} of ${mon(pol.dailyLimit)}` : mon(spentToday);
  const ok = pol.configured && pol.agent !== ZERO;
  $("vStatus").innerHTML = !pol.configured ? '<span class="tag warn">Rules not set</span>'
    : pol.paused ? '<span class="tag err">Paused</span>'
    : ok ? '<span class="tag ok">Active</span>' : '<span class="tag warn">No device approved</span>';
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
    $("polMax").placeholder = ethers.formatEther(pol.maxPerTx);
    $("polDay").placeholder = ethers.formatEther(pol.dailyLimit);
    $("polTrust").checked = pol.trustedOnly;
  }
}

async function act(label, send) {
  if (!st.writable) { msg("err", "Connect the owner's wallet first."); return; }
  try {
    msg("wait", esc(label) + "… confirm in your wallet.");
    const tx = await send();
    msg("wait", esc(label) + "… sent " + txLink(tx.hash) + ", waiting for Monad to confirm.");
    const r = await tx.wait();
    if (r.status !== 1) throw new Error("transaction failed on-chain");
    await refresh();
    msg("ok", esc(label) + " done. " + txLink(tx.hash));
  } catch (e) {
    const code = e && (e.code === "ACTION_REJECTED" || e.code === 4001);
    msg("err", code ? "You rejected the request in your wallet. Nothing changed." : esc(label) + " failed: " + esc(e.reason || e.shortMessage || e.message || e));
  }
}

function amount(id, what) {
  const v = $(id).value.trim();
  if (!/^\d*\.?\d+$/.test(v) || Number(v) <= 0) { msg("err", `Enter a ${what} greater than zero.`); return null; }
  return ethers.parseEther(v);
}

function wire() {
  $("cLink").textContent = G.address; $("cLink").href = `${G.explorer}/address/${G.address}`;
  $("connect").addEventListener("click", connect);
  $("lookupBtn").addEventListener("click", lookup);
  $("lookup").addEventListener("keydown", (e) => { if (e.key === "Enter") lookup(); });
  $("fDeposit").addEventListener("submit", (e) => { e.preventDefault(); const v = amount("depAmt", "amount"); if (v) act("Depositing", () => st.write.deposit({ value: v })); });
  $("withdrawAll").addEventListener("click", async () => { const b = await st.read.balanceOf(st.owner); if (b === 0n) { msg("err", "The vault is empty."); return; } act("Withdrawing everything", () => st.write.withdraw(b)); });
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
    window.ethereum.on("accountsChanged", () => location.reload());
    window.ethereum.on("chainChanged", () => location.reload());
  }
  const q = new URLSearchParams(location.search).get("owner");
  if (q && ethers.isAddress(q)) { $("lookup").value = q; lookup(); }
}

window.addEventListener("DOMContentLoaded", () => {
  const boot = () => (window.ethers ? wire() : setTimeout(boot, 50));
  boot();
});
