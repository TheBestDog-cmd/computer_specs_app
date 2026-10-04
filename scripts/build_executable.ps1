# Build SpecForge.exe on native Windows (PowerShell). No WSL required.
# If blocked by execution policy, run:
#   powershell -ExecutionPolicy Bypass -File .\scripts\build_executable.ps1
# Or use Command Prompt instead:
#   scripts\build_executable.bat
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "Working directory: $(Get-Location)"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python was not found on PATH. Install Python 3.10+ (64-bit) from https://www.python.org/downloads/ and check 'Add python.exe to PATH'."
}

# 32-bit Python/PyInstaller builds can under-report logical CPUs on Windows; require 64-bit.
$bitness = & python -c "import struct; print(struct.calcsize('P') * 8)"
if ($LASTEXITCODE -ne 0 -or "$bitness" -ne "64") {
    Write-Error "Need 64-bit Python to build SpecForge.exe (got ${bitness}-bit). Install the x86-64 installer from python.org."
}

python -m venv .venv
& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

# --noconsole = GUI-only (no console attached to SpecForge itself)
# --icon = desktop/taskbar/exe icon matching the in-app window icon
$icon = Join-Path (Get-Location) "assets\specforge.ico"
$verinfo = Join-Path (Get-Location) "assets\version_info.txt"
pyinstaller --noconfirm --clean --onefile --noconsole --name SpecForge `
  --icon $icon `
  --version-file $verinfo `
  --add-data "assets\specforge.ico;assets" `
  --add-data "assets\specforge.png;assets" `
  --add-data "assets\specforge_32.png;assets" `
  --add-data "assets\specforge_64.png;assets" `
  --collect-all customtkinter `
  main.py

$exe = Join-Path (Get-Location) "dist\SpecForge.exe"
if (Test-Path $exe) {
    Write-Host ""
    Write-Host "Build succeeded: $exe"
    Write-Host "Double-click that file to run SpecForge."
} else {
    Write-Error "Build finished but dist\SpecForge.exe was not found."
}
