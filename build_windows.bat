@echo off
REM Litwell, Copyright (c) 2026 J. Kent Morgan Consulting, LLC. Created by J. Kent Morgan, Ph.D.
REM Licensed under the Apache License, Version 2.0; see the LICENSE file.
REM ===================================================================
REM  Build the standalone Windows app:
REM      dist\Litwell\Litwell.exe
REM
REM  Run this ON A WINDOWS PC (not macOS). Either double-click it in
REM  File Explorer, or run  build_windows.bat  from a Command Prompt.
REM
REM  Requires Python 3.10+ from python.org, installed with BOTH:
REM    - "Add python.exe to PATH"           (checkbox on first screen)
REM    - "tcl/tk and IDLE"                  (Optional Features - leave ON)
REM ===================================================================

setlocal EnableDelayedExpansion
cd /d "%~dp0"

REM --- pick a Python to bootstrap the virtual environment -------------
set "BOOT="
where py >nul 2>&1 && set "BOOT=py -3"
if not defined BOOT (
  where python >nul 2>&1 && set "BOOT=python"
)
if not defined BOOT (
  echo ERROR: Python was not found.
  echo Install it from https://www.python.org/downloads/windows/
  echo and check "Add python.exe to PATH" during setup.
  echo.
  pause
  exit /b 1
)
echo Using Python: !BOOT!
!BOOT! --version

REM --- (re)create the virtual environment ---------------------------
REM A .venv copied from a Mac has no Scripts\python.exe - rebuild it.
if not exist ".venv\Scripts\python.exe" (
  if exist ".venv" (
    echo Removing a virtual environment that is not for Windows ...
    rmdir /s /q .venv
  )
  echo Creating virtual environment ...
  !BOOT! -m venv .venv
  if errorlevel 1 (
    echo ERROR: could not create the virtual environment.
    pause
    exit /b 1
  )
)

echo Installing dependencies (about a minute) ...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
".venv\Scripts\python.exe" -m pip install --quiet "pyinstaller>=6.3"
if errorlevel 1 (
  echo ERROR: dependency install failed. Check your internet connection.
  pause
  exit /b 1
)

REM --- confirm a working GUI toolkit --------------------------------
".venv\Scripts\python.exe" -c "import tkinter" 2>nul
if errorlevel 1 (
  echo.
  echo ERROR: this Python has no tkinter / Tcl-Tk.
  echo Re-run the python.org installer, choose "Modify", and enable
  echo the "tcl/tk and IDLE" optional feature. Then run this again.
  echo.
  pause
  exit /b 1
)

echo Cleaning previous build ...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo Building ...
".venv\Scripts\pyinstaller.exe" --noconfirm litsearch.spec
if errorlevel 1 (
  echo ERROR: the build failed. See the messages above.
  pause
  exit /b 1
)

echo.
echo ===================================================================
echo  Done.  Your app is the folder:   dist\Litwell\
echo  Run "Litwell.exe" inside it.
echo  To move it to another PC, copy or zip the WHOLE folder
echo  (the .exe needs the files next to it).
echo ===================================================================
echo.
pause
endlocal
