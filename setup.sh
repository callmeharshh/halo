#!/usr/bin/env bash
# One-shot setup for Halo on macOS. Usage: ./setup.sh
set -e
PY=$(command -v python3.12 || command -v python3.11 || command -v python3.13 || true)
[ -z "$PY" ] && { echo "Need Python 3.11-3.13 (https://www.python.org/downloads/)"; exit 1; }
echo "Using $($PY --version)"
$PY -m venv .venv
source .venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
echo
echo "✅ Installed. Next:"
echo "  1. Edit .env: add OPENAI_API_KEY and a THROWAWAY testnet WALLET_PRIVATE_KEY (faucet: https://faucet.monad.xyz)"
echo "  2. python setup_vault.py   # funds your GuardVault, sets safety limits + a demo contact"
echo "  3. python main.py"
