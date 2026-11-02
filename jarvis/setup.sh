#!/usr/bin/env bash
# JARVIS setup for bash terminals on Windows (MSYS2 / Git Bash), macOS, or Linux.
# Usage:   bash setup.sh
set -e
cd "$(dirname "$0")"
echo "============================================================"
echo "  JARVIS setup  -  this takes 5-10 minutes the first time"
echo "============================================================"

# ---- 1. Find a real Windows Python (MSYS2's own python can't install the speech packages) ----
PY=""
try_py() { "$@" -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)" >/dev/null 2>&1; }
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    LAUNCHERS=(/c/Windows/py.exe)
    [ -n "$LOCALAPPDATA" ] && LAUNCHERS+=("$(cygpath -u "$LOCALAPPDATA")/Programs/Python/Launcher/py.exe")
    for L in "${LAUNCHERS[@]}"; do
      for V in 3.12 3.11 3.13 3.10; do
        if [ -z "$PY" ] && [ -x "$L" ] && try_py "$L" -$V; then PY="$L -$V"; fi
      done
    done
    if [ -z "$PY" ] && [ -n "$LOCALAPPDATA" ]; then
      for D in "$(cygpath -u "$LOCALAPPDATA")"/Programs/Python/Python31{2,1,3,0}; do
        if [ -z "$PY" ] && [ -x "$D/python.exe" ] && try_py "$D/python.exe"; then PY="$D/python.exe"; fi
      done
    fi
    VENV_PY=".venv/Scripts/python.exe"
    ;;
  *)
    for C in python3.12 python3.11 python3.13 python3.10 python3; do
      if [ -z "$PY" ] && command -v $C >/dev/null && try_py $C; then PY=$C; fi
    done
    VENV_PY=".venv/bin/python"
    ;;
esac

if [ -z "$PY" ]; then
  echo "[X] I couldn't find Windows Python 3.10-3.13."
  echo "    Install Python 3.12 from https://www.python.org/downloads/windows/"
  echo "    (tick 'Add python.exe to PATH'), then close and reopen this terminal and run:  bash setup.sh"
  echo "    Note: MSYS2's own python (pacman) won't work - the speech packages don't support it."
  exit 1
fi
echo "[OK] Using Python: $($PY --version)  ($PY)"

# ---- 2. Private environment ----
if [ ! -x "$VENV_PY" ]; then
  echo "Creating JARVIS's own Python environment in .venv ..."
  $PY -m venv .venv
fi
echo "[OK] Environment ready."

# ---- 3. Packages ----
echo "Installing packages (lots of text will scroll past - that's normal)..."
"$VENV_PY" -m pip install --upgrade pip >/dev/null
if ! "$VENV_PY" -m pip install -r requirements.txt; then
  echo
  echo "[X] Some packages failed to install. Look for the first line with 'ERROR' above."
  echo "    Most common fix: install Python 3.12, delete the .venv folder (rm -rf .venv), run bash setup.sh again."
  exit 1
fi
echo "[OK] Packages installed."

# ---- 4. Settings ----
if [ ! -f .env ]; then cp .env.example .env; echo "[OK] Created your settings file: .env"; fi

# ---- 5. Models ----
PYTHONUNBUFFERED=1 "$VENV_PY" check.py download || echo "[!] Model download failed - JARVIS will retry on first start."

# ---- 6. 'jarvis' command ----
chmod +x jarvis 2>/dev/null || true
mkdir -p "$HOME/bin"
ln -sf "$(pwd)/jarvis" "$HOME/bin/jarvis" 2>/dev/null || cp "$(pwd)/jarvis" "$HOME/bin/jarvis"
if ! grep -q 'HOME/bin' "$HOME/.bashrc" 2>/dev/null; then
  echo 'export PATH="$HOME/bin:$PATH"' >> "$HOME/.bashrc"
fi

echo
echo "============================================================"
echo "  Setup complete!"
echo "  NEXT:  1. Put your Claude API key in .env:   nano .env"
echo "         2. Close and reopen the terminal (so the 'jarvis' command works)"
echo "         3. Test:   jarvis check mic    (then voice, wake, stt, brain)"
echo "         4. Start:  jarvis              (or 'jarvis chat' to type instead)"
echo "============================================================"
