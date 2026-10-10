"""Run the whole regression suite. Usage:
   python scripts/check_all.py            # safe: no money moves (console check spends a few cents of testnet gas)
   python scripts/check_all.py --live-tx  # also approves one real 0.05 MON payment through the server and the UI
   python scripts/check_all.py --quick    # unit + contract + site only (no OpenAI, no browser UI)
"""
import os, subprocess, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
live = "--live-tx" in sys.argv
quick = "--quick" in sys.argv
steps = [("safety unit tests", ["tests/test_safety.py"]), ("contract + repo consistency", ["tests/check_contract.py"]),
         ("public website + console (read-only)", ["tests/check_site.py"])]
if not quick:
    steps += [("agents + Scam Shield", ["tests/check_agents.py"]),
              ("travel agent (plan, sources, honesty rules, TTS)", ["tests/check_travel.py"]),
              ("server protocol", ["tests/check_server.py"] + (["--live-tx"] if live else [])),
              ("web UI end to end", ["tests/check_ui.py"] + (["--live-tx"] if live else [])),
              ("Family Console with wallet", ["tests/check_console.py"])]
results = []
for name, cmd in steps:
    t = time.time(); print(f"\n━━ {name} " + "━" * (60 - len(name)), flush=True)
    r = subprocess.run([sys.executable] + cmd, cwd=ROOT)
    results.append((name, r.returncode == 0, time.time() - t))
print("\n" + "=" * 70 + "\nSUMMARY")
for name, ok, dt in results: print(f"  {'PASS' if ok else 'FAIL'}  {name:42} {dt:5.0f}s")
bad = [n for n, ok, _ in results if not ok]
print("\n" + ("ALL CHECKS PASSED" if not bad else f"{len(bad)} SUITE(S) FAILED: {bad}"))
sys.exit(1 if bad else 0)
