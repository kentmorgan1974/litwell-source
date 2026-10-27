#!/bin/bash
# Litwell, Copyright (c) 2026 J. Kent Morgan Consulting, LLC. Created by J. Kent Morgan, Ph.D.
# Licensed under the Apache License, Version 2.0; see the LICENSE file.
# Build the standalone macOS app: dist/Litwell.app
#
# Usage:   ./build_macos.sh
# Re-run any time you change the source. Produces a fresh build each time.

set -e
cd "$(dirname "$0")"

VENV=".venv"

# Prefer the python.org build: it bundles modern Tcl/Tk 8.6, so the packaged
# .app renders correctly. macOS's built-in python3 (Tk 8.5.9) does not.
BOOTSTRAP_PY="python3"
for c in \
  /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
  /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
  /Library/Frameworks/Python.framework/Versions/3.11/bin/python3 ; do
  if [ -x "$c" ]; then BOOTSTRAP_PY="$c"; break; fi
done

if [ ! -d "$VENV" ]; then
  echo "Creating virtual environment with: $BOOTSTRAP_PY"
  "$BOOTSTRAP_PY" -m venv "$VENV"
fi

"$VENV/bin/python" -c "import tkinter as t; v=t.Tcl().call('info','patchlevel'); print('Bundled Tk:', v); import sys; sys.exit(0 if tuple(map(int,v.split('.')[:2]))>=(8,6) else 1)" || {
  echo "WARNING: this environment has old Tk (<8.6). The built app may show"
  echo "blank windows. Install Python from python.org and delete .venv, then re-run."
}

echo "Installing dependencies ..."
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r requirements.txt
"$VENV/bin/pip" install --quiet "pyinstaller>=6.3"

echo "Cleaning previous build ..."
rm -rf build dist

echo "Building ..."
"$VENV/bin/pyinstaller" --noconfirm litsearch.spec

echo
echo "Done. The app is at:  dist/Litwell.app"
echo "Drag it to /Applications, or double-click to run."
echo
echo "First launch: macOS Gatekeeper may block an unsigned app."
echo "Right-click the app -> Open -> Open, or:"
echo "  xattr -dr com.apple.quarantine \"dist/Litwell.app\""
