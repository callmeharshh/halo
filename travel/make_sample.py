"""Generate docs/sample-plan.json with the REAL agent (needs OPENAI_API_KEY). The public site shows it in 'sample mode'.
   python travel/make_sample.py"""
import json, os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "travel"))
import agent
REQ = "3 days from Pune to Goa. I use a wheelchair. Budget about 30000 rupees. I want beaches and good food, no stairs."
t = time.time()
plan = agent.plan(REQ, ["wheelchair"], "en", lambda e: print(f"  [{time.time()-t:3.0f}s] {e['text']}"))
plan["sample"] = True
plan["request"] = REQ
json.dump(plan, open(os.path.join(ROOT, "docs", "sample-plan.json"), "w"), indent=1, ensure_ascii=False)
print("wrote docs/sample-plan.json:", plan["title"], "|", len(plan["places"]), "places |", sum(len(p["access"]["sources"]) for p in plan["places"]), "sources")
