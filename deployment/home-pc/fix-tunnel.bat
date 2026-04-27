@echo off
REM ============================================================
REM  RealFlow - Fix Cloudflare Tunnel
REM  Right-click -> Run as administrator
REM ============================================================

net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Requesting Administrator privileges...
    powershell -Command "Start-Process cmd -ArgumentList '/c','\"%~f0\"' -Verb RunAs"
    exit /b 0
)

cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0fix-tunnel.ps1" %*

if errorlevel 1 (
    echo.
    pause
)
