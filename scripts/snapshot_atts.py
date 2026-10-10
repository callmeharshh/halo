"""Snapshot every AccessRegistry 'Attested' event into docs/atts.json (instant page load; the browser then scans only newer blocks).
   python scripts/snapshot_atts.py"""
import concurrent.futures as cf, json, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dotenv import load_dotenv; load_dotenv(os.path.join(ROOT, ".env"))
import wallet as wl
d = json.load(open(os.path.join(ROOT, "contracts", "deployment.AccessRegistry.json")))
c = wl.w3.eth.contract(address=d["address"], abi=d["abi"])
head = wl.with_retry(lambda: wl.w3.eth.block_number)
topic = wl.w3.keccak(text="Attested(bytes32,string,string,address,uint16,bool,string,uint256)").hex()
topic = topic if topic.startswith("0x") else "0x" + topic
chunks = [(a, min(a + 98, head)) for a in range(d["block"], head + 1, 99)]
fetch = lambda r: wl.with_retry(lambda: wl.w3.eth.get_logs({"address": d["address"], "fromBlock": r[0], "toBlock": r[1], "topics": [topic]}))
rows = []
with cf.ThreadPoolExecutor(6) as ex:
    for logs in ex.map(fetch, chunks):
        for l in logs:
            a = c.events.Attested().process_log(l)["args"]; h = l["transactionHash"].hex(); h = h if h.startswith("0x") else "0x" + h
            rows.append({"key": f"{h}:{l['logIndex']}", "tx": h, "block": l["blockNumber"], "place": a["placeName"], "city": a["city"], "by": a["by"],
                         "features": a["features"], "venueConfirmed": a["venueConfirmed"], "note": a["note"], "ts": int(a["timestamp"])})
rows.sort(key=lambda r: (r["block"], r["key"]))
json.dump({"address": d["address"], "lastBlock": head, "rows": rows}, open(os.path.join(ROOT, "docs", "atts.json"), "w"), indent=1)
print(f"snapshot: {len(rows)} attestations up to block {head} -> docs/atts.json")
