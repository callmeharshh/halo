#!/usr/bin/env bash
# One command for the LIVE demo: checks everything, then opens the live concierge at http://127.0.0.1:8780
cd "$(dirname "$0")"
source .venv/bin/activate
echo "── Preflight ──"; python travel/preflight.py || echo "(fix the ❌ items above, or continue if you are sure)"
echo; echo "── Starting the live concierge (Ctrl+C to stop) ──"
python travel/server.py
