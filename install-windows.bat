@echo off
REM ===============================================================
REM   TrackMaster - 1-Click Installer (Windows)
REM   Self-contained - .env khud create karega.
REM ===============================================================

chcp 65001 >nul 2>&1
title TrackMaster Installer
cd /d "%~dp0"

echo.
echo ===============================================================
echo       TrackMaster - 1-Click Installer
echo ===============================================================
echo.

REM ================================================================
REM  Step 1/5  Docker check
REM ================================================================
echo [1/5] Docker check...
docker --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo   ERROR: Docker Desktop install nahi hai.
    echo   Install link: https://www.docker.com/products/docker-desktop/
    echo.
    pause
    exit /b 1
)

set RETRY=0
:RETRY_DOCKER
docker ps >nul 2>&1
if %ERRORLEVEL% EQU 0 goto DOCKER_READY
set /a RETRY=%RETRY%+1
if %RETRY% LSS 8 (
    echo       Docker Engine start ho raha hai... %RETRY%/8
    timeout /t 5 /nobreak >nul
    goto RETRY_DOCKER
)
echo.
echo   ERROR: Docker Desktop chal nahi raha. Open karein aur wait karein.
pause
exit /b 1

:DOCKER_READY
echo       Docker ready hai.
echo.

REM ================================================================
REM  Step 2/5  .env file (self-heal: khud create kar deta hai)
REM ================================================================
echo [2/5] Settings file set kar raha hun...

if not exist "docker-compose.yml" (
    echo.
    echo   ERROR: docker-compose.yml nahi mila!
    echo   Aapne galat folder mein script chalaya hai.
    echo   Is file ko us folder mein rakhein jahan "backend" aur
    echo   "frontend" folders hain.
    echo.
    pause
    exit /b 1
)

if exist ".env" (
    echo       .env pehle se maujood hai.
) else (
    REM Try copying from example first (if it exists)
    if exist ".env.docker.example" (
        copy ".env.docker.example" ".env" >nul
        echo       .env copy ki gayi .env.docker.example se.
    ) else if exist "env.docker.example" (
        copy "env.docker.example" ".env" >nul
        echo       .env copy ki gayi env.docker.example se.
    ) else (
        REM Example file missing - generate a fresh .env with defaults.
        (
            echo DB_NAME=trackmaster
            echo FRONTEND_PORT=3000
            echo APP_URL=http://localhost:3000
            echo CORS_ORIGINS=*
            echo ADMIN_EMAIL=admin@trackmaster.local
            echo ADMIN_PASSWORD=admin123
            echo JWT_SECRET_KEY=change-me-to-a-long-random-string
            echo POSTBACK_TOKEN=change-me-to-a-long-random-string
            echo SMTP_HOST=smtp.gmail.com
            echo SMTP_PORT=587
            echo SMTP_USER=
            echo SMTP_PASSWORD=
            echo RESEND_API_KEY=
            echo SENDER_EMAIL=onboarding@resend.dev
        ) > .env
        echo       .env file fresh banayi default values ke saath.
    )
)
echo.

REM ================================================================
REM  Step 3/5  Build + Start
REM ================================================================
echo [3/5] App build + start...
echo       Pehli baar 5-10 min lagenge (Chromium download ~300 MB).
echo       Text chalta rahega - normal hai.
echo.
docker compose up -d --build
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo   ERROR: Build fail hua. Logs dekhein:
    echo       docker compose logs
    echo.
    pause
    exit /b 1
)
echo.

REM ================================================================
REM  Step 4/5  Ready wait
REM ================================================================
echo [4/5] App ready hone ka wait...
set TRIES=0
:WAIT_LOOP
set /a TRIES=%TRIES%+1
timeout /t 3 /nobreak >nul
curl -fsS http://localhost:3000/health >nul 2>&1
if %ERRORLEVEL% EQU 0 goto READY
if %TRIES% LSS 60 (
    echo       Wait... %TRIES%/60
    goto WAIT_LOOP
)
echo.
echo   App 3 min tak ready nahi hua.
echo   Logs dekhein:  docker compose logs -f
pause
exit /b 1

:READY
echo       App ready hai!
echo.

REM ================================================================
REM  Step 5/5  Browser
REM ================================================================
echo [5/5] Browser open...
start "" "http://localhost:3000"

echo.
echo ===============================================================
echo     DONE! TrackMaster chal raha hai.
echo ===============================================================
echo       URL:        http://localhost:3000
echo       Email:      admin@trackmaster.local
echo       Password:   admin123
echo.
echo     Stop:     docker compose down
echo     Start:    docker compose up -d
echo     Logs:     docker compose logs -f
echo.
pause
