# computer_specs_app

**SpecForge** — real-time computer specs monitor.

## Desktop app (Python GUI)

Track live inventory and usage for CPU, memory, disks, network, GPU/CUDA, temperatures, and top processes.

### Requirements

- Python 3.10+ from [python.org](https://www.python.org/downloads/)
  - Windows installer: check **Add python.exe to PATH**

### Run from source

**PowerShell**

```powershell
cd $HOME\Desktop\computer_specs_app-main
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

**Command Prompt (cmd)**

```bat
cd %USERPROFILE%\Desktop\computer_specs_app-main
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
python main.py
```

### Build a Windows exe

Prefer CMD (no PowerShell execution-policy issues):

```bat
cd %USERPROFILE%\Desktop\computer_specs_app-main
scripts\build_executable.bat
```

PowerShell one-run bypass:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_executable.ps1
```

Output: `dist\SpecForge.exe`

Build with **64-bit Python** (the scripts refuse 32-bit). A 32-bit exe can under-report logical CPUs on Windows.

### Live dashboard & scrolling

Lower panels live in one scrollable text dashboard (not a multi-frame scroll container) so wheel/scrollbar motion stays smooth while monitoring. Live meter and dashboard redraws pause briefly while you scroll, then catch up. Per-core bars come from `psutil.cpu_percent(percpu=True)`; machines with many logical cores show a compact summary plus the first/last cores.

### Temperatures on Windows (CPU / GPU)

Windows does **not** expose CPU package temperature through normal APIs (`psutil` sensors are empty there). SpecForge therefore uses several sources:

| Sensor | How SpecForge reads it | What you need |
|--------|------------------------|---------------|
| **GPU (NVIDIA)** | `nvidia-smi` (`temperature.gpu`) | Current NVIDIA drivers. `nvidia-smi` is usually in PATH or `C:\Windows\System32`. |
| **GPU (AMD)** | `amd-smi` / `rocm-smi` when installed, or LibreHardwareMonitor | AMD software / LHM |
| **CPU** | LibreHardwareMonitor or OpenHardwareMonitor WMI | Install [LibreHardwareMonitor](https://github.com/LibreHardwareMonitor/LibreHardwareMonitor), **run it (often as Administrator)**, and **leave it open** |
| **ACPI zones** | `MSAcpi_ThermalZoneTemperature` | Sometimes needs Admin; often inaccurate board zones, not true CPU package |

In the app, CPU/GPU temps appear as header meters and again in the **Temperatures** section of the live dashboard, grouped by CPU / GPU / board / other (with setup hints when a reading is unavailable).

Quick checks on your PC:

```bat
nvidia-smi --query-gpu=name,temperature.gpu --format=csv
```

If that fails, fix/install NVIDIA drivers before expecting GPU temp in SpecForge.


### CPU model on Windows

SpecForge reads the CPU brand from the Windows registry (`ProcessorNameString`) and WMI (`Win32_Processor.Name`).  
It ignores useless values like `Intel64 Family 6 Model …` that `platform.processor()` often returns.

### Updates from GitHub (including exe auto-update)

In SpecForge:

- **GitHub** — open the repository in your browser
- **Updates** → **Check** / **Update now**

Behavior:

- **Running SpecForge.exe**: downloads the latest `SpecForge.exe` from GitHub Releases and replaces itself on restart
- **Git checkout**: `git pull origin main`
- **Loose source folder**: downloads the latest source ZIP

Windows releases are published automatically by GitHub Actions on every push to `main` (workflow: `.github/workflows/release-exe.yml`).  
After this lands on `main`, wait for the Actions run to finish once so the `latest` release contains `SpecForge.exe`. Then **Update now** in the app can refresh the exe.

### Tests

```powershell
.\.venv\Scripts\Activate.ps1
pytest -q
```

### Optional web UI (Node)

```bash
npm ci
npm start
```

Open http://localhost:3000
