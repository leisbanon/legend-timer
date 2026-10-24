@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Please install dependencies first. See README.md.
  pause
  exit /b 1
)
set "PYTHONPATH=%~dp0src"
start "" ".venv\Scripts\pythonw.exe" "%~dp0run.py"
