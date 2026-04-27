@echo off
REM ============================================================
REM  RealFlow - ONE-CLICK SETUP (Windows)
REM  Right-click -> Run as administrator
REM ============================================================

REM Self-elevate to Administrator if not already
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Requesting Administrator privileges...
    powershell -Command "Start-Process cmd -ArgumentList '/c','\"%~f0\"' -Verb RunAs"
    exit /b 0
)

REM Change to script directory
cd /d "%~dp0"

echo Running RealFlow installer...
echo.

REM Launch PowerShell with execution policy bypass
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup.ps1" %*
set PS_EXIT=%errorlevel%

if %PS_EXIT% neq 0 (
    echo.
    echo ============================================================
    echo   Setup finished with errors ^(exit code: %PS_EXIT%^)
    echo   See red messages above for details.
    echo ============================================================
    pause
) else (
    echo.
    echo Setup ran successfully.
)
