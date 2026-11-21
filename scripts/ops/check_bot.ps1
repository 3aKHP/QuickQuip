# Read QuickQuip Bot status over SSH.
param(
    [string]$Server = "",
    [string]$RemoteDir = ""
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path (Split-Path $PSScriptRoot)
$connectionPython = @("$projectRoot/.venv/Scripts/python.exe", "$projectRoot/.venv/bin/python", 'python3', 'python') |
    Where-Object { Get-Command $_ -ErrorAction SilentlyContinue } | Select-Object -First 1
if (-not $connectionPython) { throw 'Local Python environment required' }
$connection = & $connectionPython -m quickquip.config_sync.deployment connection --root $projectRoot
if ($LASTEXITCODE -ne 0) { throw 'Cannot read root .env deployment connection' }
$defaults = "$connection".Split(' ')
if (-not $Server) { $Server = $defaults[0] }
if (-not $RemoteDir) { $RemoteDir = $defaults[1] }
if ($Server -cnotmatch '^[a-zA-Z0-9_][a-zA-Z0-9_.@-]*$') { throw 'Invalid SSH alias' }
if ($RemoteDir -cnotmatch '^/[a-zA-Z0-9_./-]+$' -or $RemoteDir -eq '/' -or $RemoteDir.Contains('..')) { throw 'Invalid deployment root' }

$status = ssh -o StrictHostKeyChecking=accept-new $Server "REMOTE_DIR='$RemoteDir' bash '$RemoteDir/scripts/ops/check_bot.sh' status"
if ($LASTEXITCODE -ne 0) { exit 1 }
Write-Host "QuickQuip Bot status: $status"
if ($status -ne "ONLINE") { exit 1 }
