# ============================================================
#  RealFlow - ULTIMATE Tunnel Fix (run directly from GitHub)
#
#  Usage (PowerShell as Administrator, ONE line):
#    irm https://raw.githubusercontent.com/mumair14741-sudo/mumair14741/main/fix.ps1 | iex
#
#  What it does:
#    1. Force-kills any running cloudflared processes
#    2. Uninstalls broken Windows service
#    3. Copies ALL credentials + config to SYSTEM-readable
#       C:\ProgramData\Cloudflare\cloudflared\
#    4. Rewrites config.yml to use ProgramData paths
#    5. Reinstalls service with explicit --config flag
#    6. Starts service
#    7. Waits and verifies https://api.<domain>/health
#
#  No ZIP download needed. No SETUP.bat rerun needed.
# ============================================================

$ErrorActionPreference = "Continue"

function H($t) {
    Write-Host ""
    Write-Host ("=" * 68) -ForegroundColor Cyan
    Write-Host "  $t" -ForegroundColor Cyan
    Write-Host ("=" * 68) -ForegroundColor Cyan
}
function OK($t)   { Write-Host "  [OK] $t" -ForegroundColor Green }
function S($t)    { Write-Host "  [>]  $t" -ForegroundColor White }
function W($t)    { Write-Host "  [!]  $t" -ForegroundColor Yellow }
function E($t)    { Write-Host "  [X]  $t" -ForegroundColor Red }

# -- 0. Admin check ----------------------------------------
$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
    ).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    E "This script needs Administrator privileges."
    Write-Host "  Close this window. Open PowerShell as Administrator (Win+X -> Terminal (Admin)) and paste the command again." -ForegroundColor Yellow
    return
}

H "RealFlow Ultimate Tunnel Fix"

# -- 1. Verify cloudflared present -------------------------
if (-not (Get-Command cloudflared -ErrorAction SilentlyContinue)) {
    E "cloudflared not installed."
    Write-Host "  Install it: winget install --id Cloudflare.cloudflared" -ForegroundColor Yellow
    return
}
OK "cloudflared found"

# -- 2. Locate user credentials ----------------------------
$userDir = Join-Path $env:USERPROFILE ".cloudflared"
if (-not (Test-Path (Join-Path $userDir "cert.pem"))) {
    E "No Cloudflare cert.pem found at $userDir"
    Write-Host "  Run:  cloudflared tunnel login" -ForegroundColor Yellow
    return
}
OK "Cloudflare credentials present"

# -- 3. Force kill any running cloudflared -----------------
S "Stopping any running cloudflared processes..."
$procs = Get-Process cloudflared -ErrorAction SilentlyContinue
if ($procs) {
    $procs | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}
OK "cloudflared processes killed"

# -- 4. Force stop + delete existing service --------------
S "Removing existing service (if any)..."
$svc = Get-Service cloudflared -ErrorAction SilentlyContinue
if ($svc) {
    # Use sc.exe for deterministic stop/delete - Stop-Service blocks forever
    # when the cloudflared process keeps restarting from bad config.
    cmd.exe /c "sc.exe stop cloudflared >nul 2>&1"
    Start-Sleep -Seconds 2
    # Hard kill again in case the SCM respawned it
    Get-Process cloudflared -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 1
    cmd.exe /c "sc.exe delete cloudflared >nul 2>&1"
    # Also try cloudflared's own uninstall (cleans up registry bits)
    cmd.exe /c "cloudflared --no-autoupdate service uninstall 2>&1" | Out-Null
    Start-Sleep -Seconds 2
    OK "Old service removed"
} else {
    OK "No existing service"
}

# -- 5. Copy creds to SYSTEM-readable ProgramData ----------
$sysDir = "C:\ProgramData\Cloudflare\cloudflared"
S "Copying credentials to $sysDir ..."
New-Item -ItemType Directory -Force -Path $sysDir | Out-Null
Get-ChildItem -Path $userDir -File | ForEach-Object {
    Copy-Item -Path $_.FullName -Destination $sysDir -Force -ErrorAction SilentlyContinue
    Write-Host "       * $($_.Name)" -ForegroundColor DarkGray
}
OK "Files copied"

# -- 6. Rewrite config.yml to use ProgramData paths -------
$sysCfg = Join-Path $sysDir "config.yml"
if (-not (Test-Path $sysCfg)) {
    E "config.yml missing - creating a fresh one"
    # Discover tunnel UUID from credentials file
    $credJson = Get-ChildItem -Path $sysDir -Filter "*.json" | Select-Object -First 1
    if (-not $credJson) {
        E "No tunnel credentials .json found. Run SETUP.bat first."
        return
    }
    $tunnelId = [System.IO.Path]::GetFileNameWithoutExtension($credJson.Name)
    # Ask for domain
    $domain = Read-Host "  Enter domain (e.g. realflow.online)"
    if (-not $domain) { $domain = "realflow.online" }
    $fresh = @"
tunnel: realflow
credentials-file: $sysDir\$tunnelId.json

ingress:
  - hostname: api.$domain
    service: http://localhost:8001
    originRequest:
      connectTimeout: 30s
      noTLSVerify: true
      keepAliveTimeout: 90s
  - service: http_status:404
"@
    Set-Content -Path $sysCfg -Value $fresh -Encoding UTF8
    OK "Created fresh config.yml"
} else {
    # Rewrite existing config to replace user-profile paths with ProgramData
    $cfg = Get-Content $sysCfg -Raw
    $escUser = [regex]::Escape($userDir)
    $cfg = $cfg -replace $escUser, $sysDir
    # Also handle forward-slash variants
    $cfg = $cfg -replace [regex]::Escape($userDir.Replace('\','/')), $sysDir.Replace('\','/')
    Set-Content -Path $sysCfg -Value $cfg -Encoding UTF8
    OK "config.yml paths updated"
}

# Extract domain for verification later
$cfgText = Get-Content $sysCfg -Raw
$publicDomain = "realflow.online"
if ($cfgText -match "hostname:\s*api\.([a-z0-9.-]+)") {
    $publicDomain = $Matches[1]
}

# Show final config
Write-Host ""
Write-Host "  Final config ($sysCfg):" -ForegroundColor Cyan
Get-Content $sysCfg | ForEach-Object { Write-Host "     $_" -ForegroundColor DarkGray }
Write-Host ""

# -- 7. Install service with EXPLICIT config path ---------
S "Installing cloudflared service with ProgramData config..."
# Using cmd.exe wrapper so stderr warnings don't fail PowerShell
$installOut = cmd.exe /c "cloudflared --no-autoupdate --config `"$sysCfg`" service install 2>&1"
Write-Host "       $installOut" -ForegroundColor DarkGray
Start-Sleep -Seconds 3

# -- 8. Start service --------------------------------------
S "Starting cloudflared service..."
cmd.exe /c "sc.exe start cloudflared" | Out-Null
Start-Sleep -Seconds 5

$svc = Get-Service cloudflared -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -eq "Running") {
    OK "cloudflared service is RUNNING"
} else {
    W "Service status: $($svc.Status)"
    Write-Host "       Try: sc.exe start cloudflared" -ForegroundColor Yellow
}

# -- 9. Verify public API ---------------------------------
H "Verifying public API"
S "Waiting 10s for tunnel to establish..."
Start-Sleep -Seconds 10

$url = "https://api.$publicDomain/health"
$ok = $false
for ($i = 1; $i -le 8; $i++) {
    try {
        $resp = Invoke-WebRequest -UseBasicParsing -Uri $url -TimeoutSec 8 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            OK "PUBLIC API IS LIVE: $url"
            Write-Host "       Response: $($resp.Content)" -ForegroundColor DarkGray
            $ok = $true
            break
        }
    } catch {
        Write-Host "       Attempt $i/8 - not ready yet (waiting 5s)..." -ForegroundColor DarkGray
        Start-Sleep -Seconds 5
    }
}

if ($ok) {
    Write-Host ""
    Write-Host ("=" * 68) -ForegroundColor Green
    Write-Host "  SUCCESS! Tunnel is LIVE and backend is reachable worldwide." -ForegroundColor Green
    Write-Host ("=" * 68) -ForegroundColor Green
    Write-Host ""
    Write-Host "  Open in browser: $url" -ForegroundColor White
    Write-Host "  Next: deploy frontend on Vercel with REACT_APP_BACKEND_URL=https://api.$publicDomain" -ForegroundColor White
} else {
    E "Public API still not reachable. Check tunnel logs:"
    Write-Host "     Get-Content 'C:\Windows\System32\winevt\Logs\Application.evtx' -Tail 30" -ForegroundColor Yellow
    Write-Host "  Or stream live logs by running tunnel in foreground:" -ForegroundColor Yellow
    Write-Host "     cloudflared --config `"$sysCfg`" tunnel run" -ForegroundColor Yellow
}
Write-Host ""
