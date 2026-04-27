@echo off
REM ============================================================
REM  RealFlow — Live logs (Ctrl+C to exit)
REM ============================================================
echo.
echo === RealFlow backend logs (Ctrl+C to exit) ===
echo.
docker compose logs -f backend
