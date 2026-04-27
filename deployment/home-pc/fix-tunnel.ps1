# ============================================================
#  RealFlow - Fix Cloudflare Tunnel (HTTP 530 / error 1033)
#
#  Fixes the classic issue where cloudflared Windows service
#  runs as LOCAL SYSTEM but the tunnel config + credentials are
#  in the user profile (%USERPROFILE%\.cloudflared\), which
#  LOCAL SYSTEM can't read. This copies everything to
#  C:\ProgramData\Cloudflare\cloudflared\ (SYSTEM-readable) and
#  reinstalls the service.
#
#  Run from repo: right-click fix-tunnel.bat -> Run as admin
# ============================================================

#Requires -RunAsAdministrator

$ErrorActionPreference = "Continue"

function Write-Header($t) {
    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Cyan
    Write-Host "  $t" -ForegroundColor Cyan
    Write-Host "================================================================" -ForegroundColor Cyan
}
function Write-OK($t)   { Write-Host "  [OK] $t" -ForegroundColor Green }
function Write-Step($t) { Write-Host "  [>] $t"  -ForegroundColor White }
function Write-Err($t)  { Write-Host "  [X] $t"  -ForegroundColor Red }
function Write-Warn($t) { Write-Host "  [!] $t"  -ForegroundColor Yellow }

Write-Header "RealFlow Tunnel Fix"

$userDir = Join-Path $env:USERPROFILE ".cloudflared"
$sysDir  = "C:\ProgramData\Cloudflare\cloudflared"

if (-not (Test-Path (Join-Path $userDir "config.yml"))) {
    Write-Err "No config.yml found at $userDir"
    Write-Host "  Run SETUP.bat first, then rerun this fix." -ForegroundColor Yellow
    Read-Host "Press ENTER to exit"
    exit 1
}

# Step 1: Stop existing service
Write-Step "Stopping cloudflared service..."
Stop-Service cloudflared -ErrorAction SilentlyContinue
Start-Sleep -Seconds 2

# Step 2: Uninstall existing service
Write-Step "Uninstalling cloudflared service..."
cmd.exe /c "cloudflared --no-autoupdate service uninstall 2>&1" | Out-Null
Start-Sleep -Seconds 2

# Step 3: Create ProgramData directory
Write-Step "Preparing SYSTEM-accessible config directory..."
New-Item -ItemType Directory -Force -Path $sysDir | Out-Null
Write-OK "Directory ready: $sysDir"

# Step 4: Copy ALL files from user dir to ProgramData
Write-Step "Copying cert, credentials, and config..."
Get-ChildItem -Path $userDir -File | ForEach-Object {
    Copy-Item -Path $_.FullName -Destination $sysDir -Force
    Write-Host "    * $($_.Name)" -ForegroundColor DarkGray
}
Write-OK "Files copied"

# Step 5: Rewrite config.yml to point to ProgramData paths
Write-Step "Rewriting config.yml with SYSTEM paths..."
$configPath = Join-Path $sysDir "config.yml"
$config = Get-Content $configPath -Raw
# Replace any reference to user path with ProgramData path
$escapedUser = [regex]::Escape($userDir)
$config = $config -replace $escapedUser, $sysDir
# Also handle forward slashes / mixed paths
$escapedUserForward = [regex]::Escape($userDir.Replace('\','/'))
$config = $config -replace $escapedUserForward, $sysDir.Replace('\','/')
Set-Content -Path $configPath -Value $config -Encoding UTF8
Write-OK "config.yml updated"

# Show the final config for verification
Write-Host ""
Write-Host "  Final config:" -ForegroundColor Cyan
Get-Content $configPath | ForEach-Object { Write-Host "    $_" -ForegroundColor DarkGray }
Write-Host ""

# Step 6: Reinstall cloudflared as Windows service
Write-Step "Reinstalling cloudflared service (using ProgramData config)..."
cmd.exe /c "cloudflared --no-autoupdate --config `"$configPath`" service install 2>&1" | Out-Null
Start-Sleep -Seconds 3

# Step 7: Start service
Write-Step "Starting cloudflared service..."
Start-Service cloudflared
Start-Sleep -Seconds 5

# Step 8: Verify
$svc = Get-Service cloudflared -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -eq "Running") {
    Write-OK "cloudflared service is RUNNING"
} else {
    Write-Err "Service did not start properly. Status: $($svc.Status)"
}

# Step 9: Test public API
Write-Header "Testing public API"
Write-Step "Waiting 10 seconds for tunnel to establish..."
Start-Sleep -Seconds 10

$domain = ""
if ($config -match "hostname:\s*api\.([a-z0-9.-]+)") {
    $domain = $Matches[1]
}
if (-not $domain) { $domain = "realflow.online" }

$ok = $false
for ($i = 1; $i -le 6; $i++) {
    try {
        $resp = Invoke-WebRequest -UseBasicParsing -Uri "https://api.$domain/health" -TimeoutSec 10 -ErrorAction Stop
        if ($resp.StatusCode -eq 200) {
            Write-OK "Public API is LIVE at https://api.$domain"
            Write-Host "    Response: $($resp.Content)" -ForegroundColor DarkGray
            $ok = $true
            break
        }
    } catch {
        Write-Host "    Attempt $i/6 failed (waiting 5s)..." -ForegroundColor DarkGray
        Start-Sleep -Seconds 5
    }
}

if (-not $ok) {
    Write-Warn "API still not reachable. Check with:"
    Write-Host "    cloudflared tunnel info realflow" -ForegroundColor Yellow
    Write-Host "    Get-Content 'C:\Windows\System32\config\systemprofile\.cloudflared\*.log' -Tail 30" -ForegroundColor Yellow
} else {
    Write-Host ""
    Write-Host "================================================================" -ForegroundColor Green
    Write-Host "  Tunnel is now LIVE!" -ForegroundColor Green
    Write-Host "================================================================" -ForegroundColor Green
    Write-Host "    Test in browser: https://api.$domain/health" -ForegroundColor White
}

Write-Host ""
Read-Host "Press ENTER to exit"
