"""Checks the PUBLIC website + console on GitHub Pages: live feed shows real payments, console read-only view works."""
import json, os, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import cdp

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.getenv("HALO_SITE", "https://callmeharshh.github.io/halo/")
OWNER = os.getenv("HALO_TEST_OWNER", "0xb5848eF465b06Ade36461e0f49aE2809Bae08b98")
fails = []
def check(name, ok, extra=""):
    print(("  PASS " if ok else "  FAIL ") + name + (f"  [{extra}]" if extra and not ok else ""))
    if not ok: fails.append(name)

addr = json.load(open(os.path.join(ROOT, "contracts/deployment.json")))["address"]
for page in ("", "console.html", "contract.js", "app.js", "style.css"):
    try: code = urllib.request.urlopen(SITE + page, timeout=15).status
    except Exception as e: code = str(e)
    check(f"{page or 'index'} is served (200)", code == 200, str(code))
js = urllib.request.urlopen(SITE + "contract.js", timeout=15).read().decode()
check("public contract.js points at the deployed contract", addr in js)
readme = open(os.path.join(ROOT, "README.md")).read()
check("README states the deployed contract address", addr in readme)

if not cdp.available():
    print("  SKIP browser checks (Chrome not found)")
else:
    b = cdp.Chrome()
    try:
        b.open(SITE)
        rows = b.wait("document.querySelectorAll('#feed-body tr').length > 0", 40)
        check("live feed renders on-chain payments", bool(rows))
        live = b.wait("/^Live/.test(document.querySelector('#feed-status').innerText)", 25)
        check("feed status is Live", bool(live), b.eval("document.querySelector('#feed-status').innerText"))
        check("feed shows the right contract", addr.lower() in (b.eval("document.querySelector('#live').innerText") or "").lower())
        check("site has zero console errors", not b.errors, str(b.errors[:2]))
        b.errors.clear()
        b.open(SITE + f"console.html?owner={OWNER}")
        ok = b.wait("document.querySelector('#vStatus') && document.querySelector('#vStatus').innerText.length > 1 && document.querySelector('#vStatus').innerText !== '-'", 30)
        check("console read-only view loads a vault", bool(ok))
        check("console hides management forms without a wallet", b.eval("document.querySelector('#actions').hidden") is True)
        check("console has zero console errors", not b.errors, str(b.errors[:2]))
    finally:
        b.close()
print("\nSITE CHECK:", "ALL PASSED" if not fails else f"{len(fails)} FAILED: {fails}")
sys.exit(1 if fails else 0)
