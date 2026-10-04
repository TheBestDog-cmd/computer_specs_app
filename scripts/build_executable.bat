@echo off
setlocal
cd /d "%~dp0\.."
python -m venv .venv
call .venv\Scripts\activate.bat
pip install -r requirements.txt
REM --noconsole keeps SpecForge GUI-only (no console attached to the app itself).
REM nvidia-smi refresh flashes are fixed in collector.py via CREATE_NO_WINDOW.
pyinstaller --noconfirm --clean --onefile --noconsole --name SpecForge --collect-all customtkinter main.py
echo Executable: %CD%\dist\SpecForge.exe
