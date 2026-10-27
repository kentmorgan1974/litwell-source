#!/bin/bash
# Litwell, Copyright (c) 2026 J. Kent Morgan Consulting, LLC. Created by J. Kent Morgan, Ph.D.
# Licensed under the Apache License, Version 2.0; see the LICENSE file.
# Double-click this file in Finder to start Litwell.
# It sets everything up the first time, then just launches the app.
# A Terminal window opens and stays open while the app runs - that's normal.
# You can minimize it. Closing it quits the app.

cd "$(dirname "$0")" || exit 1

echo "==================================================="
echo "  Litwell - starting up"
echo "==================================================="
echo

PY=".venv/bin/python"

# Prefer the python.org build (modern Tk 8.6, windows draw correctly) over
# macOS's built-in Python (Tk 8.5.9, blank-window bug).
BOOTSTRAP_PY=""
for c in \
  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
  /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 \
  /usr/local/bin/python3 \
  /opt/homebrew/bin/python3 \
  /usr/bin/python3 ; do
  if [ -x "$c" ]; then BOOTSTRAP_PY="$c"; break; fi
done

# First run: build the private environment and install libraries.
if [ ! -x "$PY" ]; then
  echo "First-time setup (about a minute), using: $BOOTSTRAP_PY"
  if ! "$BOOTSTRAP_PY" -m venv .venv; then
    echo
    echo "ERROR: could not create the Python environment."
    echo "Press any key to close."
    read -n 1 -s
    exit 1
  fi
  "$PY" -m pip install --quiet --upgrade pip
  "$PY" -m pip install --quiet -r requirements.txt
  echo "Setup done."
  echo
fi

# Make sure the libraries are present (in case setup was interrupted).
if ! "$PY" -c "import requests, openpyxl" 2>/dev/null; then
  echo "Installing missing libraries..."
  "$PY" -m pip install --quiet -r requirements.txt
fi

echo "Opening the app window..."
echo "(If you see a blank grey window, drag its bottom-right corner"
echo " to resize it once - that forces it to draw.)"
echo

"$PY" app.py

echo
echo "Litwell has closed. You can close this window."
