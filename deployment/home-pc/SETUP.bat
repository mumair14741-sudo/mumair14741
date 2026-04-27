@echo off
REM ============================================================
REM  RealFlow - ONE-CLICK SETUP (Windows)
REM  Double-click this file to install everything automatically.
REM ============================================================

REM Self-elevate to Administrator if not already
fsutil dirty query %systemdrive% >nul 2>&1
if errorlevel 1 (
    echo Requesting Administrator privileges...
    powershell -Command "Start-Process cmd -ArgumentList '/c','\"%~f0\"' -Verb RunAs"
    exit /b 0
)

REM Change to script directory
cd /d "%~dp0"

REM Launch the PowerShell installer, bypassing execution policy
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*

if errorlevel 1 (
    echo.
    echo Setup finished with errors. See messages above.
    pause
)
