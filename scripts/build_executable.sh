#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -r requirements.txt
# --noconsole/--windowed: GUI-only process (no console attached to SpecForge itself).
# Child-process CMD flashes on Windows are suppressed in collector.py (CREATE_NO_WINDOW).
# Icon matches the in-app window / desktop shortcut artwork.
pyinstaller \
  --noconfirm \
  --clean \
  --onefile \
  --noconsole \
  --name SpecForge \
  --icon assets/specforge.ico \
  --add-data "assets/specforge.ico:assets" \
  --add-data "assets/specforge.png:assets" \
  --collect-all customtkinter \
  main.py
echo "Executable: $ROOT/dist/SpecForge"
