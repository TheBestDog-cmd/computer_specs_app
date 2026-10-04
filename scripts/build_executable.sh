#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -r requirements.txt
pyinstaller \
  --noconfirm \
  --clean \
  --onefile \
  --windowed \
  --name SpecForge \
  --collect-all customtkinter \
  main.py
echo "Executable: $ROOT/dist/SpecForge"
