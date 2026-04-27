@echo off
REM ============================================================
REM  RealFlow — One-click START
REM  Starts Docker containers (backend + mongo) and confirms
REM  Cloudflare tunnel is running.
REM ============================================================

echo.
echo ============================================================
echo   RealFlow - Starting services
echo ============================================================
echo.

REM 1/3 — Check Docker is running
echo [1/3] Checking Docker...
docker info >nul 2>&1
if errorlevel 1 (
    echo  [X] Docker is NOT running.
    echo      Open Docker Desktop and wait for "Engine running" green dot.
    echo.
    pause
    exit /b 1
)
echo       Docker OK.

REM 2/3 — Start containers
echo.
echo [2/3] Starting containers...
docker compose up -d
if errorlevel 1 (
    echo  [X] docker compose failed. Check your .env file.
    pause
    exit /b 1
)

REM Wait for backend health
echo       Waiting for backend to become healthy...
set /a tries=0
:wait_health
timeout /t 2 /nobreak >nul
docker compose exec -T backend curl -fsS http://localhost:8001/health >nul 2>&1
if errorlevel 1 (
    set /a tries+=1
    if %tries% geq 30 (
        echo       [!] Backend not healthy after 60s. Check: docker compose logs backend
        goto tunnel_check
    )
    goto wait_health
)
echo       Backend healthy.

:tunnel_check
REM 3/3 — Cloudflare tunnel (Windows service)
echo.
echo [3/3] Cloudflare tunnel service...
sc query cloudflared >nul 2>&1
if errorlevel 1 (
    echo  [!] cloudflared service not installed.
    echo      Run (admin PowerShell):  cloudflared service install
    echo      Or manually start tunnel:  cloudflared tunnel run realflow
) else (
    net start cloudflared 2>nul
    sc query cloudflared | find "RUNNING" >nul
    if errorlevel 1 (
        echo  [X] cloudflared service not running.
    ) else (
        echo       Tunnel service RUNNING.
    )
)

echo.
echo ============================================================
echo   RealFlow is UP
echo ============================================================
echo   Frontend       : https://realflow.online
echo   Backend API    : https://api.realflow.online
echo   Local backend  : http://localhost:8001/health
echo.
echo   Stop           : stop.bat
echo   Live logs      : logs.bat
echo ============================================================
echo.
pause
