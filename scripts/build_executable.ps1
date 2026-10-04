# Build SpecForge.exe on native Windows (PowerShell). No WSL required.
# If blocked by execution policy, run:
#   powershell -ExecutionPolicy Bypass -File .\scripts\build_executable.ps1
# Or use Command Prompt instead:
#   scripts\build_executable.bat
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "Working directory: $(Get-Location)"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python was not found on PATH. Install Python 3.10+ from https://www.python.org/downloads/ and check 'Add python.exe to PATH'."
}

python -m venv .venv
& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

# --noconsole = GUI-only (no console attached to SpecForge itself)
pyinstaller --noconfirm --clean --onefile --noconsole --name SpecForge --collect-all customtkinter main.py

$exe = Join-Path (Get-Location) "dist\SpecForge.exe"
if (Test-Path $exe) {
    Write-Host ""
    Write-Host "Build succeeded: $exe"
    Write-Host "Double-click that file to run SpecForge."
} else {
    Write-Error "Build finished but dist\SpecForge.exe was not found."
}
