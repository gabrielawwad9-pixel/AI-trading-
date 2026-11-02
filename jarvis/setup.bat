@echo off
setlocal
cd /d "%~dp0"
title JARVIS setup
echo ============================================================
echo   JARVIS setup  -  this takes 5-10 minutes the first time
echo ============================================================
echo.

REM ---- 1. Find a suitable Python (3.10 - 3.13) ----
set "PY="
for %%V in (3.12 3.11 3.13 3.10) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>nul && set "PY=py -%%V"
    )
)
if not defined PY (
    python -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>nul && set "PY=python"
)
if not defined PY (
    echo [X] I couldn't find Python 3.10-3.13 on this laptop.
    echo.
    echo     Install Python 3.12 from https://www.python.org/downloads/windows/
    echo     IMPORTANT: on the first installer screen, tick "Add python.exe to PATH".
    echo     Then close this window and double-click setup.bat again.
    echo.
    pause
    exit /b 1
)
echo [OK] Found Python:
%PY% --version
echo.

REM ---- 2. Create a private Python environment for JARVIS ----
if not exist ".venv\Scripts\python.exe" (
    echo Creating JARVIS's own Python environment in .venv ...
    %PY% -m venv .venv
    if errorlevel 1 (
        echo [X] Couldn't create the environment. Try moving the JARVIS folder to Documents
        echo     and running setup.bat again.
        pause
        exit /b 1
    )
)
echo [OK] Environment ready.
echo.

REM ---- 3. Install packages ----
echo Installing packages (lots of text will scroll past - that's normal)...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [X] Some packages failed to install. Common reasons:
    echo     - No internet connection.
    echo     - Python version too new: install Python 3.12 and delete the .venv folder, then retry.
    echo     - Scroll up and look for the first line containing "ERROR" for details.
    pause
    exit /b 1
)
echo [OK] Packages installed.
echo.

REM ---- 4. Settings file ----
if not exist ".env" (
    copy ".env.example" ".env" >nul
    echo [OK] Created your settings file: .env
) else (
    echo [OK] Keeping your existing .env settings file.
)
echo.

REM ---- 5. Download models ----
".venv\Scripts\python.exe" check.py download
if errorlevel 1 (
    echo [!] Model download failed - JARVIS will try again the first time it starts.
)

echo.
echo ============================================================
echo   Setup complete!
echo.
echo   NEXT:  1. Open the .env file with Notepad and paste your Claude API key.
echo          2. Test each part:   check.bat mic   (then voice, wake, stt, brain)
echo          3. Start JARVIS:     start_jarvis.bat
echo ============================================================
pause
