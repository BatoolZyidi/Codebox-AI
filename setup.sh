#!/usr/bin/env bash
# One-time setup for macOS / Linux
set -e
cd "$(dirname "$0")"
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
echo
echo "Setup finished. Next:"
echo "  1. Open .env and paste your ASSEMBLYAI_API_KEY and GEMINI_API_KEY"
echo "  2. ./run.sh check"
echo "  3. ./run.sh run /path/to/your/project"
