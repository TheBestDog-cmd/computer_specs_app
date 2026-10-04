# computer_specs_app

**SpecForge** — real-time computer specs monitor.

## Desktop app (Python GUI)

Track live inventory and usage for:

- CPU model, physical/logical cores, per-core usage, frequency, load
- Memory & swap
- Disks and disk I/O rates
- Network interfaces and throughput
- GPU / CUDA (via `nvidia-smi` + `nvcc` when available)
- PSU / power (from Linux `power_supply` sensors when exposed)
- Temperatures and top processes

### Requirements

- Python 3.10+
- Tk (Linux: `sudo apt install python3-tk`)

### Run from source

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

### Build a single executable

```bash
bash scripts/build_executable.sh
```

The binary is written to `dist/SpecForge` (Linux/macOS) or `dist/SpecForge.exe` (Windows).

Double-click / run that file anytime — no Python install required on the target machine for the frozen build.

### Tests

```bash
source .venv/bin/activate
pytest -q
```

## Optional web UI (Node)

A lighter browser UI remains available:

```bash
npm ci
npm start
```

Open http://localhost:3000
