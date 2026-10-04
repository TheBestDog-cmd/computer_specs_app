# computer_specs_app

**SpecForge** — real-time computer specs monitor.

## Desktop app (Python GUI)

Track live inventory and usage for:

- CPU model, physical/logical cores, per-core usage, frequency, load
- Memory & swap
- Disks and disk I/O rates
- Network interfaces and throughput
- GPU / CUDA (via `nvidia-smi` + `nvcc` when available)
- PSU / power (from OS power sensors when exposed)
- Temperatures and top processes

### Requirements

- Python 3.10+ from [python.org](https://www.python.org/downloads/)
  - During install on Windows: check **Add python.exe to PATH**
- Tk (usually included with the official Windows Python installer)
- Linux only if needed: `sudo apt install python3-tk`

### Run from source

**PowerShell**

```powershell
cd $HOME\Desktop\computer_specs_app-main
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python main.py
```

If PowerShell blocks script activation:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

**Command Prompt (cmd)**

```bat
cd %USERPROFILE%\Desktop\computer_specs_app-main
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
python main.py
```

**Linux / macOS**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

### Build a single executable (Windows)

Do **not** use `bash scripts/build_executable.sh` on Windows unless you intentionally use WSL.
Build with native Windows Python instead.

**Easiest: Command Prompt (cmd)** — no execution-policy issues

```bat
cd %USERPROFILE%\Desktop\computer_specs_app-main
scripts\build_executable.bat
```

**PowerShell**

If you get “not digitally signed” / `UnauthorizedAccess`, either use the `.bat` file above, or bypass policy for one run:

```powershell
cd $HOME\Desktop\computer_specs_app-main
powershell -ExecutionPolicy Bypass -File .\scripts\build_executable.ps1
```

Or allow local scripts for your user (one-time):

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
.\scripts\build_executable.ps1
```

**PowerShell step-by-step (no script file)**

```powershell
cd $HOME\Desktop\computer_specs_app-main
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pyinstaller --noconfirm --clean --onefile --noconsole --name SpecForge --collect-all customtkinter main.py
```

**Command Prompt step-by-step**

```bat
cd %USERPROFILE%\Desktop\computer_specs_app-main
python -m venv .venv
.venv\Scripts\activate.bat
pip install -r requirements.txt
pyinstaller --noconfirm --clean --onefile --noconsole --name SpecForge --collect-all customtkinter main.py
```

Output file:

- Windows: `dist\SpecForge.exe`
- Linux/macOS: `dist/SpecForge` (use `bash scripts/build_executable.sh`)

Then double-click `dist\SpecForge.exe` anytime. No Python install is required on other PCs for that frozen build.

`--noconsole` keeps SpecForge GUI-only. Rebuild after pulling updates so `nvidia-smi` refresh calls do not flash a CMD window every second.


### Updates from GitHub

In the SpecForge window, use:

- **GitHub** — open the repository in your browser
- **Updates** — check GitHub `main` for newer commits and **Pull update**

Pull behavior:

- If the folder is a git checkout: runs `git pull origin main`
- Otherwise: downloads the latest source ZIP from GitHub into the project (or `computer_specs_app-src` next to the exe)

After pulling source updates, rebuild the Windows exe:

```bat
scripts\build_executable.bat
```

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
