@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo [X] JARVIS isn't set up yet. Double-click setup.bat first.
    exit /b 1
)
".venv\Scripts\python.exe" trade.py %*
