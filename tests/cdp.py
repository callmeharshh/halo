"""Tiny synchronous headless-Chrome driver (Chrome DevTools Protocol) for the regression checks."""
import base64, json, os, shutil, socket, subprocess, tempfile, time, urllib.request
from websockets.sync.client import connect

CHROME = os.getenv("CHROME_BIN", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")


def available() -> bool:
    return os.path.exists(CHROME)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Chrome:
    def __init__(self, width=1280, height=900):
        self.port = _free_port()
        self.profile = tempfile.mkdtemp(prefix="halo-chrome-")
        self.proc = subprocess.Popen(
            [CHROME, "--headless=new", "--disable-gpu", f"--remote-debugging-port={self.port}",
             f"--user-data-dir={self.profile}", f"--window-size={width},{height}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.errors: list[str] = []
        self._id = 0
        for _ in range(60):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json", timeout=2))
                self.ws = connect([t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"], max_size=None)
                break
            except Exception:
                time.sleep(0.5)
        else:
            raise RuntimeError("could not start Chrome")
        for m in ("Runtime.enable", "Page.enable", "Log.enable"):
            self.send(m)

    def send(self, method, **params):
        self._id += 1
        my = self._id
        self.ws.send(json.dumps({"id": my, "method": method, "params": params}))
        while True:
            r = json.loads(self.ws.recv(timeout=90))
            if r.get("method") == "Runtime.exceptionThrown":
                d = r["params"]["exceptionDetails"]
                self.errors.append("exception: " + (d.get("exception", {}).get("description") or d.get("text", ""))[:200])
            elif r.get("method") == "Runtime.consoleAPICalled" and r["params"]["type"] == "error":
                self.errors.append("console.error: " + " ".join(str(a.get("value", a.get("description", ""))) for a in r["params"]["args"])[:200])
            if r.get("id") == my:
                return r.get("result", {})

    def open(self, url, preload: str | None = None, settle=2.0):
        if preload:
            self.send("Page.addScriptToEvaluateOnNewDocument", source=preload)
        self.send("Page.navigate", url=url)
        time.sleep(settle)

    def eval(self, expr):
        r = self.send("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in r:
            return None
        return r.get("result", {}).get("value")

    def wait(self, expr, timeout=30, interval=0.5):
        end = time.time() + timeout
        while time.time() < end:
            v = self.eval(expr)
            if v:
                return v
            time.sleep(interval)
        return None

    def screenshot(self, path, full=True):
        r = self.send("Page.captureScreenshot", format="png", captureBeyondViewport=full)
        open(path, "wb").write(base64.b64decode(r["data"]))

    def close(self):
        try:
            self.ws.close()
        finally:
            self.proc.terminate()
            shutil.rmtree(self.profile, ignore_errors=True)


MOCK_WALLET = """
(() => {
  const KEY = '%s';
  let wallet, rpc;
  const boot = () => { if (!wallet) { rpc = new ethers.JsonRpcProvider('https://testnet-rpc.monad.xyz'); wallet = new ethers.Wallet(KEY, rpc); } };
  window.ethereum = { isMock: true, on() {},
    async request({method, params}) {
      boot();
      if (method === 'eth_requestAccounts' || method === 'eth_accounts') return [wallet.address];
      if (method === 'eth_chainId') return '0x279f';
      if (method === 'net_version') return '10143';
      if (method === 'wallet_switchEthereumChain' || method === 'wallet_addEthereumChain') return null;
      if (method === 'eth_sendTransaction') { const t = params[0]; const tx = await wallet.sendTransaction({to: t.to, data: t.data, value: t.value ? BigInt(t.value) : 0n}); return tx.hash; }
      return rpc.send(method, params || []);
    } };
})();
"""


def mock_wallet(private_key: str) -> str:
    return MOCK_WALLET % private_key
