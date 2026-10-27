@echo off
REM Litwell, Copyright (c) 2026 J. Kent Morgan Consulting, LLC. Created by J. Kent Morgan, Ph.D.
REM Licensed under the Apache License, Version 2.0; see the LICENSE file.
REM ===================================================================
REM  Build a SINGLE-FILE Windows app:
REM      dist\Litwell.exe
REM
REM  This is the one to give to someone else - it's just one file.
REM  (Slightly slower to start than the folder version, because it
REM   unpacks itself to a temp folder on each launch.)
REM
REM  Run this ON A WINDOWS PC. Double-click it, or run from a
REM  Command Prompt.  Same Python requirements as build_windows.bat.
REM ===================================================================

setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "BOOT="
where py >nul 2>&1 && set "BOOT=py -3"
if not defined BOOT (
  where python >nul 2>&1 && set "BOOT=python"
)
if not defined BOOT (
  echo ERROR: Python was not found. Install it from
  echo https://www.python.org/downloads/windows/ with "Add python.exe to PATH".
  echo.
  pause
  exit /b 1
)
echo Using Python: !BOOT!
!BOOT! --version

if not exist ".venv\Scripts\python.exe" (
  if exist ".venv" (
    echo Removing a virtual environment that is not for Windows ...
    rmdir /s /q .venv
  )
  echo Creating virtual environment ...
  !BOOT! -m venv .venv
  if errorlevel 1 ( echo ERROR: could not create the virtual environment. & pause & exit /b 1 )
)

echo Installing dependencies (about a minute) ...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
".venv\Scripts\python.exe" -m pip install --quiet "pyinstaller>=6.3"
if errorlevel 1 ( echo ERROR: dependency install failed. Check your internet connection. & pause & exit /b 1 )

".venv\Scripts\python.exe" -c "import tkinter" 2>nul
if errorlevel 1 (
  echo.
  echo ERROR: this Python has no tkinter / Tcl-Tk. Re-run the python.org
  echo installer, choose "Modify", and enable "tcl/tk and IDLE".
  echo.
  pause
  exit /b 1
)

echo Cleaning previous build ...
if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

echo Building single-file app ...
set "LITSEARCH_ONEFILE=1"
".venv\Scripts\pyinstaller.exe" --noconfirm litsearch.spec
set "LITSEARCH_ONEFILE="
if errorlevel 1 ( echo ERROR: the build failed. See the messages above. & pause & exit /b 1 )

echo.
echo ===================================================================
echo  Done.  Give this ONE file to anyone with 64-bit Windows 10 or 11:
echo.
echo      dist\Litwell.exe
echo.
echo  They double-click it - no install, no Python needed.
echo  First launch: "Windows protected your PC" -^> More info -^> Run anyway.
echo ===================================================================
echo.
pause
endlocal
