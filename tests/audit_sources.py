"""Citation audit: for every source link in the sample plan, fetch the page and measure whether it is reachable and actually
mentions accessibility. This measures how well the cited sources back the claims (it cannot prove a claim is true).
   python tests/audit_sources.py"""
import json, os, re, sys, concurrent.futures as cf
import requests
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KW = re.compile(r"wheelchair|accessib|step[- ]free|ramp|lift|elevator|disab|assistance|braille|tactile|hearing loop|mobility", re.I)
plan = json.load(open(os.path.join(ROOT, "docs", "sample-plan.json")))
jobs = [(p["name"], s["title"], s["url"]) for p in plan["places"] for s in p["access"]["sources"]]
def check(j):
    name, title, url = j
    if "maps.google" in url or "google.com/maps" in url:
        return (name, url, "google-listing", None)  # official Places data; verified through the API, not a scrapable page
    try:
        r = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"})
        if r.status_code != 200:
            return (name, url, f"unverifiable (HTTP {r.status_code})", None)
        hits = len(KW.findall(re.sub(r"<[^>]+>", " ", r.text)))
        return (name, url, "ok" if hits >= 3 else "reachable but few accessibility terms", hits)
    except Exception as e:
        return (name, url, "unreachable", None)
with cf.ThreadPoolExecutor(6) as ex: res = list(ex.map(check, jobs))
from collections import Counter
c = Counter(r[2] for r in res)
for n, u, st, h in res: print(f"  {st:42} {n[:30]:30} {u[:70]}")
ok = sum(1 for r in res if r[2] in ("ok", "google-listing"))
print(f"\nSOURCES: {len(res)} | supported (page mentions accessibility, or official Google listing): {ok} | {dict(c)}")
print("Note: 'unverifiable' usually means the site blocks scripts; open the link manually before quoting it.")
