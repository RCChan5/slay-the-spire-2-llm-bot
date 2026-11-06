@echo off
rem Starts the StsBot dashboard (this PC only) and opens it in the browser.
cd /d "%~dp0"
start "" http://localhost:8765
if defined STSBOT_PYTHON (set PY=%STSBOT_PYTHON%) else if exist "%~dp0.venv\Scripts\python.exe" (set PY=%~dp0.venv\Scripts\python.exe) else (set PY=python)
"%PY%" -m stsbot.dashboard
