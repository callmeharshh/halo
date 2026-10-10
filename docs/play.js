/* "Try to move money": a READ-ONLY dry run against the real GuardVault contract, as Ramesh's device.
   Uses eth_call (no gas, no wallet, moves no money) so the answer is the contract's real answer for the real demo vault. */
(function () {
  const G = window.GUARDVAULT; if (!G) return;
  const OWNER = "0xb5848eF465b06Ade36461e0f49aE2809Bae08b98";          // the demo family vault
  const STRANGER = "0x9f3a" + "0".repeat(32) + "c21e";                   // a wallet nobody trusts
  const ABI = [
    "function policyOf(address) view returns (bool configured, bool trustedOnly, bool paused, uint128 maxPerTx, uint128 dailyLimit, address agent)",
    "function balanceOf(address) view returns (uint256)", "function spentInDay(address) view returns (uint256)", "function currentDay(address) view returns (uint256)",
    "function contactsOf(address) view returns (string[] names, address[] addrs)",
    "function guardedSend(address owner, string contactName, address to, uint256 amount, string approvedBy)",
  ];
  const $ = (id) => document.getElementById(id);
  const mon = (w) => { const s = ethers.formatEther(w); return (s.includes(".") ? s.replace(/0+$/, "").replace(/\.$/, "") : s); };
  const WHY = {
    "exceeds per-transaction limit": "That is above the family's per-payment limit.",
    "exceeds daily limit": "That would go over today's daily limit.",
    "recipient not a saved contact": "That person is not one of the family's trusted contacts.",
    "unknown contact": "Halo doesn't know that contact.",
    "paused by owner": "The family has paused payments.",
    "insufficient vault balance": "There isn't enough money in the vault.",
    "not owner or agent": "This device isn't approved by the family.",
  };
  let urlsIdx = 0, rules = null;

  async function withProvider(fn) {
    const urls = G.rpcs || [G.rpc]; let last;
    for (let i = 0; i < urls.length * 2; i++) {
      try {
        const prov = new ethers.JsonRpcProvider(urls[(urlsIdx + i) % urls.length], G.chainId, { staticNetwork: true, batchMaxCount: 1 });
        const r = await fn(prov); urlsIdx = (urlsIdx + i) % urls.length; return r;
      } catch (e) { if (e && e.code === "CALL_EXCEPTION" && e.reason) throw e; last = e; await new Promise((r) => setTimeout(r, 200 * (i + 1))); }
    }
    throw last;
  }

  async function loadRules() {
    try {
      const [pol, bal, spent, day, book] = await withProvider(async (prov) => {
        const c = new ethers.Contract(G.address, ABI, prov);
        return Promise.all([c.policyOf(OWNER), c.balanceOf(OWNER), c.spentInDay(OWNER), c.currentDay(OWNER), c.contactsOf(OWNER)]);
      });
      const today = BigInt(Math.floor(Date.now() / 1000 / 86400));
      const left = pol.dailyLimit - (day === today ? spent : 0n);
      rules = { agent: pol.agent, max: pol.maxPerTx, daily: pol.dailyLimit, left };
      $("tr-max").textContent = mon(pol.maxPerTx) + " MON"; $("tr-day").textContent = mon(pol.dailyLimit) + " MON (" + mon(left < 0n ? 0n : left) + " left today)";
      $("tr-who").textContent = pol.trustedOnly ? "Trusted contacts only" : "Anyone"; $("tr-bal").textContent = mon(bal) + " MON";
      $("tr-state").textContent = !pol.configured ? "Rules not set" : pol.paused ? "Paused" : "Active";
      $("tr-contacts").textContent = book.names.length ? book.names.join(", ") : "none";
      $("tryBtn").disabled = false;
    } catch (e) { $("tr-state").textContent = "Could not reach Monad. Try again."; }
  }

  async function ask() {
    if (!rules) return;
    const toStranger = $("tryWho").value === "stranger";
    const amt = Number($("tryAmt").value);
    const box = $("tryOut"), btn = $("tryBtn");
    if (!(amt > 0)) { box.dataset.kind = "err"; $("tryHead").textContent = "Pick an amount first."; $("tryWhy").textContent = ""; $("tryRaw").textContent = ""; return; }
    btn.disabled = true; box.dataset.kind = "wait"; $("tryHead").textContent = "Asking the contract on Monad…"; $("tryWhy").textContent = ""; $("tryRaw").textContent = "";
    const who = toStranger ? "the unknown wallet 0x9f3a…c21e" : "Alice";
    try {
      const wei = ethers.parseEther(String(amt));
      const iface = new ethers.Interface(ABI);
      const data = iface.encodeFunctionData("guardedSend", [OWNER, toStranger ? "" : "alice", toStranger ? STRANGER : ethers.ZeroAddress, wei, "demo"]);
      await withProvider((prov) => prov.call({ from: rules.agent, to: G.address, data }));   // success = would be allowed
      box.dataset.kind = "ok"; $("tryHead").textContent = "Allowed";
      $("tryWhy").textContent = `The contract would let Halo send ${amt} MON to ${who}. (Dry run: nothing was sent.)`; $("tryRaw").textContent = "guardedSend(…) → success";
    } catch (e) {
      let reason = (e && (e.reason || (e.info && e.info.error && e.info.error.message) || e.shortMessage || "")) + "";
      const m = reason.match(/execution reverted:?\s*(.*)$/i); if (m && m[1]) reason = m[1];
      reason = reason.replace(/^"|"$/g, "").trim();
      const known = Object.keys(WHY).find((k) => reason.includes(k));
      if (known) {
        box.dataset.kind = "bad"; $("tryHead").textContent = "Rejected by the contract";
        $("tryWhy").textContent = WHY[known] + ` Halo cannot send ${amt} MON to ${who}, whatever anyone says.`; $("tryRaw").textContent = "revert: " + known;
      } else { box.dataset.kind = "err"; $("tryHead").textContent = "Couldn't get an answer"; $("tryWhy").textContent = "The network was slow. Please try again."; $("tryRaw").textContent = reason.slice(0, 90); }
    } finally { btn.disabled = false; }
  }

  function wire() {
    if (!$("tryBtn")) return;
    $("tryBtn").addEventListener("click", ask);
    $("tryAmt").addEventListener("input", () => { $("tryAmtVal").textContent = $("tryAmt").value + " MON"; });
    document.querySelectorAll("[data-amt]").forEach((b) => b.addEventListener("click", () => { $("tryAmt").value = b.dataset.amt; $("tryAmtVal").textContent = b.dataset.amt + " MON"; ask(); }));
    $("tryAmtVal").textContent = $("tryAmt").value + " MON";
    loadRules();
  }
  window.addEventListener("DOMContentLoaded", () => { const boot = () => (window.ethers ? wire() : setTimeout(boot, 60)); boot(); });
})();
