@echo off
rem Starts the bot in this window with the dashboard's saved settings. Close the window or press Ctrl+C to stop it.
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
"C:\SAS\.venv\Scripts\python.exe" -m tools.start
pause
