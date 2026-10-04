@echo off
setlocal EnableExtensions
cd /d "%~dp0\.."

echo Working directory: %CD%

where python >nul 2>nul
if errorlevel 1 (
  echo ERROR: Python was not found on PATH.
  echo Install Python 3.10+ ^(64-bit^) from https://www.python.org/downloads/
  echo and check "Add python.exe to PATH", then reopen this terminal.
  exit /b 1
)

REM 32-bit Python/PyInstaller builds can under-report logical CPUs on Windows.
for /f %%B in ('python -c "import struct; print(struct.calcsize('P') * 8)"') do set PYBITS=%%B
if not "%PYBITS%"=="64" (
  echo ERROR: Need 64-bit Python to build SpecForge.exe ^(got %PYBITS%-bit^).
  echo Install the Windows x86-64 installer from python.org.
  exit /b 1
)

python -m venv .venv
if errorlevel 1 exit /b 1

call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 exit /b 1

REM --noconsole keeps SpecForge GUI-only (no console attached to the app itself).
REM nvidia-smi refresh flashes are suppressed in collector.py via CREATE_NO_WINDOW.
pyinstaller --noconfirm --clean --onefile --noconsole --name SpecForge --collect-all customtkinter main.py
if errorlevel 1 exit /b 1

if not exist "dist\SpecForge.exe" (
  echo ERROR: dist\SpecForge.exe was not created.
  exit /b 1
)

echo.
echo Build succeeded: %CD%\dist\SpecForge.exe
echo Double-click that file to run SpecForge.
