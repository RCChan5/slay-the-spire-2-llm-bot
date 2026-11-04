@echo off
rem Starts the StsBot dashboard (this PC only) and opens it in the browser.
cd /d "%~dp0"
start "" http://localhost:8765
"C:\SAS\.venv\Scripts\python.exe" -m stsbot.dashboard
