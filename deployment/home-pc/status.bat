@echo off
REM ============================================================
REM  RealFlow — STATUS check
REM  Quick health check for all services
REM ============================================================
echo.
echo =============== RealFlow Status Check ===============
echo.

echo [Docker]
docker compose ps 2>nul
if errorlevel 1 (
    echo   [X] Docker not running OR no containers
) else (
    echo.
)

echo [Backend local]
curl -s -o nul -w "  /health -> HTTP %%{http_code}\n" http://localhost:8001/health 2>nul
if errorlevel 1 echo   [X] Backend not reachable locally

echo.
echo [Cloudflare Tunnel]
sc query cloudflared | findstr "STATE" 2>nul
if errorlevel 1 echo   [X] cloudflared service not installed

echo.
echo [Public API]
curl -s -o nul -w "  https://api.realflow.online/health -> HTTP %%{http_code}\n" https://api.realflow.online/health 2>nul

echo.
echo [Frontend]
curl -s -o nul -w "  https://realflow.online -> HTTP %%{http_code}\n" https://realflow.online 2>nul

echo.
echo =====================================================
pause
