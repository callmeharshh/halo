"""Headless-Chrome (CDP) end-to-end driver for the Halo UI against dev_mock_server.py.
Usage: ../../.venv/bin/python e2e.py [base_url] [out_dir]
Needs: websockets. Wallet mock (EIP-1193, signs with a throwaway testnet key and really sends Monad testnet txs)
reads the key from $HALO_TEST_KEY_FILE."""
import asyncio, base64, json, os, subprocess, sys, time, urllib.request
import websockets

CH = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8799/"
OUT = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), "shots")
KEYFILE = os.environ.get("HALO_TEST_KEY_FILE", "/private/tmp/claude-501/-Users-harsh-Desktop-Projects-Hackathon-Project/9809e303-5647-425e-bb27-241f6489bab1/scratchpad/family.key")
os.makedirs(OUT, exist_ok=True)
MOCK = """
(() => {
  const KEY = '%s'; let wallet, rpc;
  const boot = () => { if (!wallet) { rpc = new ethers.JsonRpcProvider('https://testnet-rpc.monad.xyz'); wallet = new ethers.Wallet(KEY, rpc); } };
  window.ethereum = { isMock: true, on() {}, async request({method, params}) {
    boot();
    if (method === 'eth_requestAccounts' || method === 'eth_accounts') return [wallet.address];
    if (method === 'eth_chainId') return '0x279f';
    if (method === 'net_version') return '10143';
    if (method === 'wallet_switchEthereumChain' || method === 'wallet_addEthereumChain') return null;
    if (method === 'eth_sendTransaction') { const t = params[0]; const tx = await wallet.sendTransaction({to: t.to, data: t.data, value: t.value ? BigInt(t.value) : 0n}); return tx.hash; }
    return rpc.send(method, params || []);
  } };
})();
""" % open(KEYFILE).read().strip()

class Page:
    def __init__(self, c): self.c, self.i, self.errs = c, 0, []
    async def call(self, m, **pr):
        self.i += 1; my = self.i
        await self.c.send(json.dumps({"id": my, "method": m, "params": pr}))
        while True:
            r = json.loads(await self.c.recv())
            p = r.get("params", {})
            if r.get("method") == "Runtime.exceptionThrown": self.errs.append(json.dumps(p["exceptionDetails"])[:300])
            if r.get("method") == "Runtime.consoleAPICalled" and p["type"] == "error": self.errs.append("console.error " + str([a.get("value", a.get("description")) for a in p["args"]])[:300])
            if r.get("method") == "Log.entryAdded" and p["entry"]["level"] == "error": self.errs.append("log " + p["entry"]["text"] + " " + p["entry"].get("url", ""))
            if r.get("id") == my: return r.get("result", {})
    async def ev(self, expr):
        r = await self.call("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        return r.get("result", {}).get("value", r.get("exceptionDetails"))
    async def shot(self, name, full=False):
        r = await self.call("Page.captureScreenshot", format="png", captureBeyondViewport=full)
        open(f"{OUT}/{name}.png", "wb").write(base64.b64decode(r["data"])); print("shot", name)
    async def size(self, w, h, mobile=False):
        await self.call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=mobile)
    async def until(self, expr, t=60):
        t0 = time.time()
        while time.time() - t0 < t:
            v = await self.ev(expr)
            if v: return v
            await asyncio.sleep(0.25)
        return None

async def main():
    p = subprocess.Popen([CH, "--headless=new", "--disable-gpu", "--remote-debugging-port=9335", "--user-data-dir=/private/tmp/claude-501/cdp-prof-halo", "--window-size=1280,800", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            try: tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9335/json")); break
            except Exception: time.sleep(0.5)
        ws = [t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"]
        async with websockets.connect(ws, max_size=None) as c:
            pg = Page(c)
            for d in ("Runtime", "Page", "Log"): await pg.call(d + ".enable")
            await pg.call("Page.addScriptToEvaluateOnNewDocument", source=MOCK)
            await pg.size(1280, 800)
            await pg.call("Page.navigate", url=BASE)
            await pg.until("document.getElementById('vaultVal') && document.getElementById('vaultVal').textContent.includes('MON')", 15)
            await asyncio.sleep(1); await pg.shot("01_idle")
            await pg.ev("document.getElementById('micBtn').click()"); await asyncio.sleep(1); await pg.shot("02_listening")
            await pg.ev("(()=>{const i=document.getElementById('typeIn');i.value='hello there';document.getElementById('typeForm').requestSubmit()})()")
            await asyncio.sleep(1.4); await pg.shot("03_hearing")
            await asyncio.sleep(1.5); await pg.shot("04_thinking")
            await asyncio.sleep(1.5); await pg.shot("05_speaking")
            await asyncio.sleep(4)
            await pg.ev("(()=>{const i=document.getElementById('typeIn');i.value='send 0.05 to alice';document.getElementById('typeForm').requestSubmit()})()")
            assert await pg.until("!document.getElementById('confirmOv').hidden", 10), "confirm did not appear"
            await asyncio.sleep(2.5); await pg.shot("06_confirm")
            print("focus on:", await pg.ev("document.activeElement.id"))
            await pg.ev("document.getElementById('cfYes').click()")
            assert await pg.until("document.getElementById('confirmOv').hidden", 5), "confirm did not hide"
            await asyncio.sleep(3.5); await pg.shot("07_success")
            print("toast:", await pg.ev("document.getElementById('toasts').innerText"))
            # keyboard: M toggles mic
            await pg.ev("document.activeElement.blur()")
            await pg.call("Input.dispatchKeyEvent", type="keyDown", key="m", text="m"); await pg.call("Input.dispatchKeyEvent", type="keyUp", key="m")
            await asyncio.sleep(0.6); print("mic after M:", await pg.ev("document.getElementById('micState').textContent"))
            # Family
            await pg.ev("document.getElementById('tab-family').click()"); await asyncio.sleep(1.2)
            await pg.shot("08_family_disconnected")
            print("qr visible:", await pg.ev("!document.getElementById('qrBlock').hidden"))
            await pg.ev("document.getElementById('connect').click()")
            assert await pg.until("document.getElementById('msg').dataset.kind=='ok'", 40), "connect failed: " + str(await pg.ev("document.getElementById('msg').innerText"))
            await asyncio.sleep(0.5); await pg.shot("09_family_connected")
            await pg.ev("document.getElementById('oneBtn').click()")
            r = await pg.until("(()=>{const m=document.getElementById('msg');return (m.dataset.kind=='ok'&&/owns this device|Approved and sent/.test(m.innerText))||m.dataset.kind=='err'?m.dataset.kind+' | '+m.innerText:''})()", 90)
            print("one-click ->", r)
            await asyncio.sleep(0.5); await pg.shot("10_family_after_oneclick", full=True)
            print("recorded:", [m for m in json.load(urllib.request.urlopen(BASE + "dev/last")) if m.get("type") == "set_owner"])
            print("owner shown:", await pg.ev("document.getElementById('devOwner').textContent"))
            # responsive
            for w, h, n in ((768, 1024, "tablet"), (390, 844, "phone")):
                await pg.size(w, h, mobile=(w < 500))
                for tab in ("companion", "family"):
                    await pg.ev(f"document.getElementById('tab-{tab}').click()"); await asyncio.sleep(0.6)
                    sw = await pg.ev("[document.documentElement.scrollWidth, innerWidth]")
                    print(n, tab, "scrollWidth/innerWidth", sw)
                    await pg.shot(f"11_{n}_{tab}", full=True)
            print("ERRORS:", pg.errs)
    finally:
        p.terminate()
asyncio.run(main())
