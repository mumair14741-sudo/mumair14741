@echo off
REM ============================================================
REM  RealFlow - One-click STOP
REM ============================================================

echo.
echo ============================================================
echo   RealFlow - Stopping services
echo ============================================================
echo.

echo [1/2] Stopping Docker containers...
docker compose down
echo.

echo [2/2] Stopping Cloudflare tunnel service...
net stop cloudflared 2>nul
echo.

echo ============================================================
echo   RealFlow is DOWN
echo ============================================================
echo   Restart with:  start.bat
echo ============================================================
echo.
pause
