@echo off
REM ============================================================
REM  RealFlow — Update (git pull + rebuild)
REM ============================================================
echo.
echo === RealFlow Update ===
echo.

echo [1/3] Pulling latest code from GitHub...
git pull
if errorlevel 1 (
    echo  [X] git pull failed. Resolve manually.
    pause
    exit /b 1
)
echo.

echo [2/3] Rebuilding containers...
docker compose up -d --build
echo.

echo [3/3] Cleaning unused images...
docker image prune -f
echo.

echo === Update complete ===
echo Live:  https://realflow.online
pause
