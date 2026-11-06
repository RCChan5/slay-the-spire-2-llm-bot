@echo off
rem Starts the bot in this window with the dashboard's saved settings. Close the window or press Ctrl+C to stop it.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
if defined STSBOT_PYTHON (set PY=%STSBOT_PYTHON%) else if exist "%~dp0.venv\Scripts\python.exe" (set PY=%~dp0.venv\Scripts\python.exe) else (set PY=python)
"%PY%" -m tools.start
pause
