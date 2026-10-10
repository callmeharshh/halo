"""Verify the deployed GuardVault on Sourcify (MonadVision) using the exact standard-json input used to deploy."""
import json
import os
import sys

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
CONTRACT_NAME = sys.argv[1] if len(sys.argv) > 1 else "GuardVault"
d = json.load(open(os.path.join(HERE, "deployment.json" if CONTRACT_NAME == "GuardVault" else f"deployment.{CONTRACT_NAME}.json")))
BASE = "https://sourcify-api-monad.blockvision.org"
addr, chain = d["address"], str(d["chainId"])

body = {
    "stdJsonInput": d["standardInput"],
    "compilerVersion": d["solc"] + "+commit.730da8bd" if False else d["solc"],
    "contractIdentifier": f"contracts/{CONTRACT_NAME}.sol:{CONTRACT_NAME}",
}
# Sourcify v2 wants the full compiler version string (e.g. 0.8.26+commit.8a97fa7a)
import solcx
body["compilerVersion"] = str(solcx.get_solc_version(solcx.get_executable(f"v{d['solc']}"))) if False else None

def full_version():
    import subprocess
    exe = solcx.install.get_executable(d["solc"])
    out = subprocess.run([str(exe), "--version"], capture_output=True, text=True).stdout
    return out.strip().split("Version: ")[1].replace(".Darwin.appleclang", "").replace(".Linux.g++", "").split("\n")[0].split(".Darwin")[0]

body["compilerVersion"] = full_version()
print("compiler:", body["compilerVersion"])
r = requests.post(f"{BASE}/v2/verify/{chain}/{addr}", json=body, timeout=60)
print("v2 verify:", r.status_code, r.text[:400])
if r.status_code in (200, 202):
    vid = r.json().get("verificationId")
    import time
    for _ in range(20):
        time.sleep(3)
        s = requests.get(f"{BASE}/v2/verify/{vid}", timeout=30).json()
        print("status:", {k: s.get(k) for k in ("isJobCompleted", "error")}, (s.get("contract") or {}).get("match"))
        if s.get("isJobCompleted"):
            break
chk = requests.get(f"{BASE}/v2/contract/{chain}/{addr}", timeout=30)
print("lookup:", chk.status_code, chk.text[:300])
