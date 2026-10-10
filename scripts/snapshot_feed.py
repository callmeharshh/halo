"""Snapshot every GuardedTransfer since deployment into docs/feed.json so the public site shows full history instantly
(the browser then only scans blocks newer than the snapshot). Re-run + commit before submitting and after demo payments:
    python scripts/snapshot_feed.py
"""
import concurrent.futures as cf, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv; load_dotenv(os.path.join(ROOT, ".env"))
import wallet as wl

d = json.load(open(os.path.join(ROOT, "contracts/deployment.json")))
topic = wl.w3.keccak(text="GuardedTransfer(address,address,string,uint256,string,uint256)").hex()
topic = topic if topic.startswith("0x") else "0x" + topic
head = wl.with_retry(lambda: wl.w3.eth.block_number)
ev = wl.vault.events.GuardedTransfer()
chunks = [(a, min(a + 98, head)) for a in range(d["block"], head + 1, 99)]

def fetch(r):
    a, b = r
    return wl.with_retry(lambda: wl.w3.eth.get_logs({"address": d["address"], "fromBlock": a, "toBlock": b, "topics": [topic]}))

rows = []
with cf.ThreadPoolExecutor(6) as ex:
    for logs in ex.map(fetch, chunks):
        for l in logs:
            p = ev.process_log(l)["args"]
            h = l["transactionHash"].hex(); h = h if h.startswith("0x") else "0x" + h
            rows.append({"key": f"{h}:{l['logIndex']}", "tx": h, "block": l["blockNumber"], "to": p["to"], "contact": p["contactName"],
                         "amount": str(p["amount"]), "approvedBy": p["approvedBy"], "ts": int(p["timestamp"])})
rows.sort(key=lambda r: (r["block"], r["key"]))
json.dump({"address": d["address"], "lastBlock": head, "rows": rows}, open(os.path.join(ROOT, "docs/feed.json"), "w"), indent=1)
print(f"snapshot: {len(rows)} transfers up to block {head} -> docs/feed.json")
