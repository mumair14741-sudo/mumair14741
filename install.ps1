# ============================================================
#  RealFlow - ONE-LINER Installer
#
#  Users run:
#     irm https://raw.githubusercontent.com/<OWNER>/<REPO>/main/install.ps1 | iex
#
#  This script:
#    1. Verifies admin privileges
#    2. Installs Git if missing
#    3. Clones the repo to Desktop\realflow
#    4. Hands off to deployment\home-pc\setup.ps1 (the main installer)
# ============================================================

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# ── CONFIG: update these if you fork the repo ─────────────
$GITHUB_OWNER = "mumair14741-sudo"
$GITHUB_REPO  = "mumair14741"
$BRANCH       = "main"
$CLONE_DIR    = Join-Path $env:USERPROFILE "Desktop\realflow"
# ───────────────────────────────────────────────────────────

function Write-Header($text) {
    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host "  $text" -ForegroundColor Cyan
    Write-Host "================================================================" -ForegroundColor Cyan
}
function Write-OK($t)   { Write-Host "  [OK] $t" -ForegroundColor Green }
function Write-Step($t) { Write-Host "  [>] $t"  -ForegroundColor White }
function Write-Err($t)  { Write-Host "  [X] $t"  -ForegroundColor Red }

Write-Header "RealFlow - One-Line Installer"
Write-Host "  Repo:  https://github.com/$GITHUB_OWNER/$GITHUB_REPO" -ForegroundColor DarkGray
Write-Host "  Into:  $CLONE_DIR" -ForegroundColor DarkGray

# ── Step 1: Admin check + self-elevate ────────────────────
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
$isAdmin = $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    Write-Host ""
    Write-Host "  This installer needs Administrator privileges." -ForegroundColor Yellow
    Write-Host "  Relaunching in an elevated window..." -ForegroundColor Yellow

    $url = "https://raw.githubusercontent.com/$GITHUB_OWNER/$GITHUB_REPO/$BRANCH/install.ps1"
    $cmd = "irm '$url' | iex"
    Start-Process powershell -ArgumentList "-NoExit","-NoProfile","-ExecutionPolicy","Bypass","-Command",$cmd -Verb RunAs
    exit 0
}

# ── Step 2: Install Git if missing ─────────────────────────
Write-Header "Step 1/3 : Checking Git"
if (Get-Command git -ErrorAction SilentlyContinue) {
    Write-OK "Git already installed"
} else {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        Write-Err "winget is not available on this PC."
        Write-Host "  Install 'App Installer' from the Microsoft Store, then rerun." -ForegroundColor Yellow
        Read-Host "Press ENTER to exit"
        exit 1
    }
    Write-Step "Installing Git via winget..."
    winget install --id Git.Git -e --silent --accept-package-agreements --accept-source-agreements | Out-Null
    $env:PATH = "C:\Program Files\Git\cmd;$env:PATH"
    if (Get-Command git -ErrorAction SilentlyContinue) {
        Write-OK "Git installed"
    } else {
        Write-Err "Git install failed. Close this window and reopen PowerShell as admin, then rerun."
        Read-Host "Press ENTER to exit"
        exit 1
    }
}

# ── Step 3: Clone or update the repo ───────────────────────
Write-Header "Step 2/3 : Getting the source code"
if (Test-Path (Join-Path $CLONE_DIR ".git")) {
    Write-Step "Repo already exists at $CLONE_DIR — pulling latest..."
    Push-Location $CLONE_DIR
    git pull --quiet
    Pop-Location
    Write-OK "Repo up-to-date"
} else {
    Write-Step "Cloning to $CLONE_DIR ..."
    git clone --quiet "https://github.com/$GITHUB_OWNER/$GITHUB_REPO.git" $CLONE_DIR
    if (-not (Test-Path (Join-Path $CLONE_DIR ".git"))) {
        Write-Err "git clone failed. Check your internet + repo URL."
        Read-Host "Press ENTER to exit"
        exit 1
    }
    Write-OK "Repo cloned"
}

# ── Step 4: Hand off to the main setup script ─────────────
Write-Header "Step 3/3 : Launching full setup"
$setupScript = Join-Path $CLONE_DIR "deployment\home-pc\setup.ps1"
if (-not (Test-Path $setupScript)) {
    Write-Err "setup.ps1 not found at $setupScript"
    Write-Host "  This usually means the repo is outdated or wrong branch." -ForegroundColor Yellow
    Read-Host "Press ENTER to exit"
    exit 1
}

Write-OK "Starting setup.ps1 ..."
& $setupScript
