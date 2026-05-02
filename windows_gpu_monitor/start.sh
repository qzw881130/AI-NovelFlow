#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$SCRIPT_DIR"

printf '==========================================\n'
printf 'GPU Monitor Service\n'
printf '==========================================\n\n'

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  printf 'ERROR: Python not found\n' >&2
  exit 1
fi

if [ ! -d "venv" ]; then
  printf 'Creating virtual environment...\n'
  "$PYTHON_BIN" -m venv venv
fi

printf 'Activating virtual environment...\n'
source venv/bin/activate

printf 'Installing dependencies...\n'
pip install -q -r requirements.txt

printf '\nStarting GPU Monitor Service...\n'
printf 'URL: http://localhost:9999/gpu-stats\n\n'

python gpu_monitor.py
