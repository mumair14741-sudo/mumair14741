# ============================================================
#  RealFlow - One-Click Windows Installer
#  Requires: Windows 10/11, admin rights, internet connection
#
#  This script does EVERYTHING:
#    1. Installs Git, Docker Desktop, Cloudflared (if missing)
#    2. Generates secure random secrets (JWT / POSTBACK)
#    3. Creates .env with your domain + admin credentials
#    4. Logs into Cloudflare (browser popup - one click to authorize)
#    5. Creates + configures the tunnel (api.<yourdomain>)
#    6. Installs tunnel as a Windows service (auto-start on boot)
#    7. Starts Docker containers (backend + mongo + chromium)
#    8. Adds a startup shortcut so everything auto-starts on boot
#    9. Verifies the API is live on https://api.<yourdomain>/health
#
#  Run from the project root:
#    Right-click SETUP.bat -> Run as Administrator
# ============================================================

#Requires -RunAsAdministrator

param(
    [string]$Domain,
    [string]$AdminEmail,
    [SecureString]$AdminPassword
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

# --- Output helpers ----------------------------------------
function Write-Header($text) {
    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host "  $text" -ForegroundColor Cyan
    Write-Host "================================================================" -ForegroundColor Cyan
}
function Write-Step($text)    { Write-Host "  [>] $text" -ForegroundColor White }
function Write-OK($text)      { Write-Host "  [OK] $text" -ForegroundColor Green }
function Write-Warn($text)    { Write-Host "  [!] $text"  -ForegroundColor Yellow }
function Write-Err($text)     { Write-Host "  [X] $text"  -ForegroundColor Red }
function Write-Skip($text)    { Write-Host "  [=] $text (already done, skipping)" -ForegroundColor DarkGray }

function Pause-For-Enter($msg = "Press ENTER to continue...") {
    Write-Host ""
    Read-Host $msg
}

# Always work from the repo root (parent of this script's folder)
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent (Split-Path -Parent $ScriptDir)
Set-Location $RepoRoot

Write-Header "RealFlow One-Click Installer"
Write-Host "  Working directory: $RepoRoot" -ForegroundColor DarkGray
Write-Host ""

# --- Phase 1: Prerequisites --------------------------------
Write-Header "Phase 1/7 : Checking prerequisites"

# 1.1 - Winget (needed to install everything else)
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Err "winget is not installed."
    Write-Host "  Install the 'App Installer' from the Microsoft Store, then rerun." -ForegroundColor Yellow
    Pause-For-Enter "Press ENTER to exit..."
    exit 1
}
Write-OK "winget available"

# 1.2 - Git
if (Get-Command git -ErrorAction SilentlyContinue) {
    Write-Skip "Git installed"
} else {
    Write-Step "Installing Git..."
    winget install --id Git.Git -e --silent --accept-package-agreements --accept-source-agreements | Out-Null
    $env:PATH = "C:\Program Files\Git\cmd;$env:PATH"
    Write-OK "Git installed"
}

# 1.3 - Docker Desktop
$dockerInstalled = (Get-Command docker -ErrorAction SilentlyContinue) -ne $null
if ($dockerInstalled) {
    Write-Skip "Docker installed"
} else {
    Write-Step "Installing Docker Desktop (this takes ~5 min)..."
    winget install --id Docker.DockerDesktop -e --silent --accept-package-agreements --accept-source-agreements | Out-Null
    Write-OK "Docker Desktop installed"
    Write-Warn "PC restart required so WSL2 can activate."
    Write-Host "    After restart, open Docker Desktop and wait for 'Engine running'." -ForegroundColor Yellow
    Write-Host "    Then rerun SETUP.bat - it will skip what is already done." -ForegroundColor Yellow
    Pause-For-Enter "Press ENTER to exit..."
    exit 0
}

# 1.4 - Docker Desktop running?
Write-Step "Checking Docker Desktop is running..."
try {
    docker info 2>$null | Out-Null
    Write-OK "Docker Desktop running"
} catch {
    Write-Err "Docker Desktop is NOT running."
    Write-Host "    Open Docker Desktop from Start menu, wait for the green 'Engine running' dot, then rerun this script." -ForegroundColor Yellow
    Pause-For-Enter "Press ENTER to exit..."
    exit 1
}

# 1.5 - Cloudflared
if (Get-Command cloudflared -ErrorAction SilentlyContinue) {
    Write-Skip "cloudflared installed"
} else {
    Write-Step "Installing cloudflared..."
    winget install --id Cloudflare.cloudflared -e --silent --accept-package-agreements --accept-source-agreements | Out-Null
    $env:PATH = "C:\Program Files (x86)\cloudflared;$env:PATH"
    Write-OK "cloudflared installed"
}

# --- Phase 2: Gather inputs --------------------------------
Write-Header "Phase 2/7 : Configuration"

# Use existing .env if present, otherwise prompt
$envPath = Join-Path $RepoRoot ".env"
$existingEnv = @{}
if (Test-Path $envPath) {
    Write-Step "Existing .env found - keeping previous values (secrets will NOT be regenerated)."
    Get-Content $envPath | Where-Object { $_ -match "^[^#].*=" } | ForEach-Object {
        $parts = $_ -split '=', 2
        $existingEnv[$parts[0].Trim()] = $parts[1].Trim().Trim('"')
    }
}

if (-not $Domain) {
    $defaultDom = if ($existingEnv["APP_URL"]) { ($existingEnv["APP_URL"] -replace '^https?://','') } else { "realflow.online" }
    $Domain = Read-Host "  Domain name (e.g. realflow.online) [$defaultDom]"
    if ([string]::IsNullOrWhiteSpace($Domain)) { $Domain = $defaultDom }
}
$Domain = $Domain.Trim().ToLower() -replace '^https?://','' -replace '/$',''
Write-OK "Domain: $Domain (backend will be at api.$Domain)"

if (-not $AdminEmail) {
    $defaultEmail = if ($existingEnv["ADMIN_EMAIL"]) { $existingEnv["ADMIN_EMAIL"] } else { "admin@$Domain" }
    $AdminEmail = Read-Host "  Admin email [$defaultEmail]"
    if ([string]::IsNullOrWhiteSpace($AdminEmail)) { $AdminEmail = $defaultEmail }
}
Write-OK "Admin email: $AdminEmail"

if (-not $AdminPassword) {
    if ($existingEnv["ADMIN_PASSWORD"] -and $existingEnv["ADMIN_PASSWORD"] -notmatch "CHANGE_ME") {
        $reuse = Read-Host "  Keep existing admin password? [Y/n]"
        if ($reuse -ne "n") {
            $AdminPassword = ConvertTo-SecureString $existingEnv["ADMIN_PASSWORD"] -AsPlainText -Force
        }
    }
    if (-not $AdminPassword) {
        $pwd1 = Read-Host "  Admin password (min 8 chars)" -AsSecureString
        $pwd2 = Read-Host "  Confirm password" -AsSecureString
        $p1 = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($pwd1))
        $p2 = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($pwd2))
        if ($p1 -ne $p2) { Write-Err "Passwords do not match."; exit 1 }
        if ($p1.Length -lt 8) { Write-Err "Password must be at least 8 characters."; exit 1 }
        $AdminPassword = $pwd1
    }
}
$AdminPasswordPlain = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($AdminPassword)
)
Write-OK "Admin password set (hidden)"

# --- Phase 3: Generate secrets + write .env ----------------
Write-Header "Phase 3/7 : Generating .env"

function New-HexSecret([int]$bytes = 32) {
    $buf = New-Object byte[] $bytes
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($buf)
    return ($buf | ForEach-Object { $_.ToString("x2") }) -join ""
}

$JwtSecret = if ($existingEnv["JWT_SECRET_KEY"] -and $existingEnv["JWT_SECRET_KEY"] -notmatch "CHANGE_ME") { $existingEnv["JWT_SECRET_KEY"] } else { New-HexSecret 32 }
$PostbackToken = if ($existingEnv["POSTBACK_TOKEN"] -and $existingEnv["POSTBACK_TOKEN"] -notmatch "CHANGE_ME") { $existingEnv["POSTBACK_TOKEN"] } else { New-HexSecret 32 }

$envContent = @"
# Auto-generated by SETUP.bat on $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")
# DO NOT commit this file to Git (.gitignore already covers it).

# Public URLs
APP_URL=https://$Domain
CORS_ORIGINS=https://$Domain,https://www.$Domain

# Database
DB_NAME=realflow

# Admin seed
ADMIN_EMAIL=$AdminEmail
ADMIN_PASSWORD=$AdminPasswordPlain

# Security
JWT_SECRET_KEY=$JwtSecret
POSTBACK_TOKEN=$PostbackToken

# Email (optional)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
RESEND_API_KEY=
SENDER_EMAIL=onboarding@resend.dev

# Local frontend port (only used with --profile local-frontend)
FRONTEND_PORT=3000
"@
Set-Content -Path $envPath -Value $envContent -Encoding UTF8
Write-OK ".env written"

# --- Phase 4: Cloudflare Tunnel ----------------------------
Write-Header "Phase 4/7 : Cloudflare Tunnel setup"

$cfDir = Join-Path $env:USERPROFILE ".cloudflared"
New-Item -ItemType Directory -Force -Path $cfDir | Out-Null

# 4.1 - Login (only if cert.pem missing)
$certPath = Join-Path $cfDir "cert.pem"
if (Test-Path $certPath) {
    Write-Skip "Cloudflare login (cert.pem present)"
} else {
    Write-Step "Launching Cloudflare login in your browser..."
    Write-Host "     >>> A browser window will open. Select '$Domain' and click 'Authorize'." -ForegroundColor Yellow
    Start-Sleep -Seconds 2
    & cloudflared tunnel login
    if (-not (Test-Path $certPath)) {
        Write-Err "Cloudflare login did not complete."
        Write-Host "    Make sure the domain is added to Cloudflare and try again." -ForegroundColor Yellow
        exit 1
    }
    Write-OK "Logged in to Cloudflare"
}

# 4.2 - Create tunnel (idempotent)
Write-Step "Checking tunnel 'realflow'..."

# Helper: cloudflared sometimes prints a version-warning JSON line before
# the actual tunnel list. Capture raw output and extract only the JSON array.
function Get-CloudflareTunnels {
    $raw = & cloudflared --no-autoupdate tunnel list --output json 2>&1 | Out-String
    $start = $raw.IndexOf('[')
    $end   = $raw.LastIndexOf(']')
    if ($start -ge 0 -and $end -gt $start) {
        try { return ($raw.Substring($start, $end - $start + 1) | ConvertFrom-Json) }
        catch { return @() }
    }
    return @()
}

$tunnelList = Get-CloudflareTunnels
$tunnel = $tunnelList | Where-Object { $_.name -eq "realflow" } | Select-Object -First 1
if ($tunnel) {
    Write-Skip "Tunnel 'realflow' already exists (id: $($tunnel.id))"
} else {
    Write-Step "Creating tunnel 'realflow'..."
    & cloudflared --no-autoupdate tunnel create realflow 2>&1 | Out-Null
    $tunnelList = Get-CloudflareTunnels
    $tunnel = $tunnelList | Where-Object { $_.name -eq "realflow" } | Select-Object -First 1
    if (-not $tunnel) { Write-Err "Failed to create tunnel"; exit 1 }
    Write-OK "Tunnel created (id: $($tunnel.id))"
}
$TunnelId = $tunnel.id

# 4.3 - Config file
$configPath = Join-Path $cfDir "config.yml"
$credFile = (Join-Path $cfDir "$TunnelId.json") -replace '\\','\\'
$configContent = @"
tunnel: realflow
credentials-file: $credFile

ingress:
  - hostname: api.$Domain
    service: http://localhost:8001
    originRequest:
      connectTimeout: 30s
      noTLSVerify: true
      keepAliveTimeout: 90s
  - service: http_status:404
"@
Set-Content -Path $configPath -Value $configContent -Encoding UTF8
Write-OK "Tunnel config written"

# 4.4 - DNS route (idempotent - ignores "already exists" error)
Write-Step "Routing api.$Domain -> tunnel..."
& cloudflared --no-autoupdate tunnel route dns realflow "api.$Domain" 2>&1 | ForEach-Object {
    if ($_ -match "already exists|record already") {
        Write-Skip "DNS record already exists"
    } else {
        Write-Host "    $_" -ForegroundColor DarkGray
    }
}
Write-OK "DNS routed"

# 4.5 - Install as Windows service
Write-Step "Installing cloudflared as Windows service..."
$svc = Get-Service cloudflared -ErrorAction SilentlyContinue
if ($svc) {
    Write-Skip "cloudflared service already installed"
    if ($svc.Status -ne "Running") {
        Start-Service cloudflared
        Write-OK "cloudflared service started"
    }
} else {
    & cloudflared service install 2>&1 | Out-Null
    Start-Sleep -Seconds 3
    Start-Service cloudflared -ErrorAction SilentlyContinue
    Write-OK "cloudflared service installed + started"
}

# --- Phase 5: Start Docker containers ----------------------
Write-Header "Phase 5/7 : Starting Docker containers"

Write-Step "Building images and starting containers (first time ~5-10 min)..."
docker compose up -d --build
if ($LASTEXITCODE -ne 0) {
    Write-Err "docker compose failed. Check the output above."
    exit 1
}

Write-Step "Waiting for backend to become healthy..."
$tries = 0
$healthy = $false
while ($tries -lt 60) {
    Start-Sleep -Seconds 3
    try {
        $resp = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:8001/health" -TimeoutSec 3 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) { $healthy = $true; break }
    } catch { }
    $tries++
    if ($tries % 5 -eq 0) { Write-Host "    ...still waiting (${tries}/60)" -ForegroundColor DarkGray }
}
if ($healthy) { Write-OK "Backend healthy on http://localhost:8001" }
else { Write-Warn "Backend did not become healthy in 3 min. Run 'docker compose logs backend' to investigate." }

# --- Phase 6: Startup on boot ------------------------------
Write-Header "Phase 6/7 : Auto-start on boot"

$startupDir = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup"
$shortcutPath = Join-Path $startupDir "RealFlow-Start.lnk"
$startBat = Join-Path $ScriptDir "start.bat"

if (Test-Path $shortcutPath) {
    Write-Skip "Startup shortcut already exists"
} else {
    $WshShell = New-Object -ComObject WScript.Shell
    $shortcut = $WshShell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $startBat
    $shortcut.WorkingDirectory = $RepoRoot
    $shortcut.WindowStyle = 7  # Minimized
    $shortcut.Description = "RealFlow - auto-start backend on boot"
    $shortcut.Save()
    Write-OK "Startup shortcut created"
}

# Also ensure Docker Desktop starts on login
$dockerDesktopStartup = Join-Path $startupDir "Docker Desktop.lnk"
if (-not (Test-Path $dockerDesktopStartup)) {
    Write-Warn "Docker Desktop auto-start not detected."
    Write-Host "    Open Docker Desktop, go to Settings > General, and enable auto-start on login." -ForegroundColor Yellow
}

# --- Phase 7: Verification ---------------------------------
Write-Header "Phase 7/7 : Verifying public API"

Write-Step "Testing https://api.$Domain/health ..."
Start-Sleep -Seconds 5  # give tunnel + DNS a moment
$publicOK = $false
for ($i = 0; $i -lt 5; $i++) {
    try {
        $resp = Invoke-WebRequest -UseBasicParsing -Uri "https://api.$Domain/health" -TimeoutSec 10 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            $publicOK = $true
            Write-OK "Public API is LIVE at https://api.$Domain"
            break
        }
    } catch {
        Start-Sleep -Seconds 4
    }
}
if (-not $publicOK) {
    Write-Warn "Public API not reachable yet. Common causes:"
    Write-Host "    - DNS still propagating (wait 1-2 min and try: curl https://api.$Domain/health)" -ForegroundColor Yellow
    Write-Host "    - Tunnel service not running (Get-Service cloudflared)" -ForegroundColor Yellow
    Write-Host "    - Backend not healthy (docker compose logs backend)" -ForegroundColor Yellow
}

# --- Final summary -----------------------------------------
Write-Header "All Done!"
Write-Host ""
Write-Host "  Your backend is installed and running." -ForegroundColor Green
Write-Host ""
Write-Host "  Local checks:" -ForegroundColor White
Write-Host "    http://localhost:8001/health        -> backend health" -ForegroundColor DarkGray
Write-Host "    https://api.$Domain/health   -> public API" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Admin credentials:" -ForegroundColor White
Write-Host "    Email:    $AdminEmail" -ForegroundColor DarkGray
Write-Host "    Password: (the one you entered)" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  Daily controls (double-click the .bat files in deployment\home-pc\):" -ForegroundColor White
Write-Host "    start.bat   stop.bat   logs.bat   status.bat   update.bat" -ForegroundColor DarkGray
Write-Host ""
Write-Host "  NEXT: Deploy the frontend on Vercel" -ForegroundColor Yellow
Write-Host "    1. https://vercel.com/new -> Import your GitHub repo" -ForegroundColor Yellow
Write-Host "    2. Root Directory: frontend    Framework: Create React App" -ForegroundColor Yellow
Write-Host "    3. Build Command: CI=false yarn build" -ForegroundColor Yellow
Write-Host "    4. Environment Variable: REACT_APP_BACKEND_URL = https://api.$Domain" -ForegroundColor Yellow
Write-Host "    5. Deploy -> Settings -> Domains -> add $Domain" -ForegroundColor Yellow
Write-Host ""
Pause-For-Enter "Press ENTER to exit..."
