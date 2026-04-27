@echo off
REM ============================================================
REM  RealFlow - BOOTSTRAP Installer
REM  Download this one file to any folder (e.g. Desktop), then
REM  double-click. It will:
REM    1. Install Git if missing
REM    2. Clone the RealFlow repo into Desktop\realflow
REM    3. Run SETUP.bat (the full installer)
REM
REM  Update GITHUB_URL below with your repo's clone URL.
REM ============================================================

set "GITHUB_URL=https://github.com/mumair14741-sudo/mumair14741.git"
set "CLONE_DIR=%USERPROFILE%\Desktop\realflow"

echo.
echo ============================================================
echo   RealFlow - Bootstrap
echo ============================================================
echo   Repo:  %GITHUB_URL%
echo   Into:  %CLONE_DIR%
echo ============================================================
echo.

REM Elevate to admin
fsutil dirty query %systemdrive% >nul 2>&1
if errorlevel 1 (
    echo Requesting Administrator privileges...
    powershell -Command "Start-Process cmd -ArgumentList '/c','\"%~f0\"' -Verb RunAs"
    exit /b 0
)

REM 1. Install Git if missing
where git >nul 2>&1
if errorlevel 1 (
    echo [1/3] Installing Git...
    winget install --id Git.Git -e --silent --accept-package-agreements --accept-source-agreements
    set "PATH=C:\Program Files\Git\cmd;%PATH%"
) else (
    echo [1/3] Git already installed - skipping.
)

REM 2. Clone or update the repo
if exist "%CLONE_DIR%\.git" (
    echo [2/3] Repo already cloned - pulling latest...
    cd /d "%CLONE_DIR%"
    git pull
) else (
    echo [2/3] Cloning repo...
    git clone "%GITHUB_URL%" "%CLONE_DIR%"
    if errorlevel 1 (
        echo  [X] git clone failed. Check the URL and your internet.
        pause
        exit /b 1
    )
)

REM 3. Launch the main installer
echo [3/3] Launching SETUP.bat...
echo.
cd /d "%CLONE_DIR%\deployment\home-pc"
call SETUP.bat

echo.
echo Bootstrap complete.
pause
