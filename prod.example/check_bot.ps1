# QuickQuip Bot status checker and QR login helper.
# Usage:
#   .\prod\check_bot.ps1
#   .\prod\check_bot.ps1 -ForceRecreate

param(
    [string]$Server = "quickquip-prod",
    [string]$RemoteDir = "/opt/QuickQuip",
    [switch]$ForceRecreate
)

$ErrorActionPreference = "Stop"

function Write-Step($msg) { Write-Host $msg -ForegroundColor Cyan }
function Write-OK($msg) { Write-Host $msg -ForegroundColor Green }
function Write-Err($msg) { Write-Host $msg -ForegroundColor Red }

function Invoke-Server($cmd) {
    $full = "bash $RemoteDir/prod/check_bot.sh $cmd"
    $result = ssh -o StrictHostKeyChecking=no $Server $full 2>&1 | ForEach-Object { "$_" }
    $result = ($result -join "`n").Trim()
    if ($LASTEXITCODE -ne 0) {
        Write-Err "SSH failed: $result"
        return $null
    }
    return $result
}

Write-Step "=== QuickQuip Bot status check ==="
Write-Host "Server: $Server"

Write-Step "[1/2] Checking status..."
$statusResult = Invoke-Server "status"
if ($null -eq $statusResult) { exit 1 }

$status = $statusResult.Trim()
$statusColor = if ($status -eq "ONLINE" -and -not $ForceRecreate) { "Green" } else { "Yellow" }
Write-Host "Bot status: $status" -ForegroundColor $statusColor

if ($status -eq "ONLINE" -and -not $ForceRecreate) {
    Write-OK "Bot is online."
    exit 0
}

if ($status -eq "IDLE" -and -not $ForceRecreate) {
    Write-Host "Container is running but no recent heartbeat/activity was found." -ForegroundColor Yellow
    Write-Host "Suggested action: [G] restart LLBot to get a new QR code." -ForegroundColor Yellow
}

$action = ""
if ($ForceRecreate) {
    $action = "f"
}
else {
    Write-Host ""
    Write-Host "Available actions:" -ForegroundColor Yellow
    Write-Host "  [G] Restart LLBot and get a new QR code"
    Write-Host "  [F] Force recreate session data and start fresh"
    Write-Host "  [Q] Quit"
    while ($action -notin @("g", "f", "q")) {
        $action = (Read-Host "Choose [G/F/Q]").ToLower()
    }
}

if ($action -eq "q") {
    Write-Host "Canceled."
    exit 0
}

Write-Step "[2/2] Getting QR code..."
$serverCmd = if ($action -eq "f") { "force-recreate" } else { "gen-qr" }
$qrResult = Invoke-Server $serverCmd
if ($null -eq $qrResult) { exit 1 }

Write-Host $qrResult

$qrUrl = ""
foreach ($line in ($qrResult -split "`n")) {
    if ($line -match "^QR:(https://.+)$") {
        $qrUrl = $Matches[1]
        break
    }
}

if (-not $qrUrl) {
    Write-Err "Could not extract QR URL from LLBot logs."
    Write-Host "Try WebUI via: ssh -L 3080:127.0.0.1:3080 $Server, then open http://127.0.0.1:3080"
    exit 1
}

$rawQrUrl = $qrUrl
$match = [regex]::Match($qrUrl, 'data=(https?%3A%2F%2F[^&]+)')
if ($match.Success) {
    $rawQrUrl = [System.Web.HttpUtility]::UrlDecode($match.Groups[1].Value)
}

Write-Host ""
Write-Step "QR URL: $rawQrUrl"
Write-Host "Rendering terminal QR code..."
Write-Host ""

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"

$pyScript = @"
import sys
try:
    import qrcode
except ImportError:
    print('qrcode is not installed. Run: pip install qrcode')
    sys.exit(1)

qr = qrcode.QRCode(border=2)
qr.add_data('$rawQrUrl')
qr.make(fit=True)
qr.print_ascii(invert=True)
print()
print('Scan the QR code with mobile QQ.')
"@

if (Test-Path $venvPython) {
    $pyScript | & $venvPython - 2>$null
} else {
    Write-Host "Project venv Python not found ($venvPython)"
    Write-Host ""
    Write-Host "Copy this URL or use the WebUI tunnel:"
    Write-Host "  $rawQrUrl" -ForegroundColor Green
    Write-Host "  ssh -L 3080:127.0.0.1:3080 $Server" -ForegroundColor Cyan
    Write-Host "  then open http://127.0.0.1:3080"
}

Write-Host ""
Write-Step "Waiting for login... (up to 120 seconds)"
$loginResult = Invoke-Server "wait-login 120"
if ($null -eq $loginResult) { exit 1 }

$loginStatus = $loginResult.Trim()
if ($loginStatus -eq "ONLINE") {
    Write-OK "Bot is online."
} else {
    Write-Err "Timed out. Check whether the QR code was scanned."
    Write-Host "If this repeats, try: .\prod\check_bot.ps1 -ForceRecreate" -ForegroundColor Yellow
}
