#!/usr/bin/env bash
# Usage: ./run.sh [run|chat|check|devices|index] [project-folder]
START_DIR="$PWD"
cd "$(dirname "$0")"
source .venv/bin/activate
CMD="${1:-run}"
REPO="${2:-$START_DIR}"
python -m codebox "$CMD" --repo "$REPO"
