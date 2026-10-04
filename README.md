# computer_specs_app

**SpecForge** — real-time computer specs monitor.

## Desktop app (Python GUI)

Track live inventory and usage for CPU, memory, disks, network, GPU/CUDA, power, temperatures, and top processes.

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
