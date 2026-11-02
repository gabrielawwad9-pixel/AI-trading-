@echo off
cd /d "%~dp0"
title JARVIS
if not exist ".venv\Scripts\python.exe" (
    echo [X] JARVIS isn't set up yet. Double-click setup.bat first.
    pause
    exit /b 1
)
".venv\Scripts\python.exe" jarvis.py %*
pause
