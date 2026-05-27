# QuickQuip production deploy script (IPv4 / PowerShell)
# Usage: run from project root:
#   .\prod\deploy-v4.ps1
# Local archive check:
#   .\prod\deploy-v4.ps1 -LocalCheck

param(
    [switch]$LocalCheck,
    [string]$HostAlias = "quickquip-prod",
    [string]$RemoteDir = "/opt/QuickQuip"
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$TempArchive = "$env:TEMP\quickquip-deploy.tar.gz"
$TiebaStateArchive = "$env:TEMP\quickquip-tieba-state.tar.gz"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$LocalPrivateWorkspace = "d" + "ev"
$TiebaStateFile = "data/tieba/storage_state.json"
$SendkeyEnvFile = "prod/sendkey.env"
$FontFile = "data/fonts/NotoSansSC-Regular.ttf"
$SshArgs = @(
    "-o", "StrictHostKeyChecking=no",
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=15",
    "-o", "ServerAliveInterval=15",
    "-o", "ServerAliveCountMax=3"
)
$ScpArgs = @(
    "-o", "StrictHostKeyChecking=no",
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=15",
    "-o", "ServerAliveInterval=15",
    "-o", "ServerAliveCountMax=3"
)

function Initialize-NodeToolchainPath {
    $preferred = @()
    $voltaProgram = "C:\Program Files\Volta"
    $voltaUserBin = Join-Path $env:LOCALAPPDATA "Volta\bin"
    foreach ($path in @($voltaProgram, $voltaUserBin)) {
        if ($path -and (Test-Path $path)) {
            $preferred += $path
        }
    }

    $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    $items = @()
    foreach ($path in ($preferred + ($env:Path -split ';'))) {
        if (-not $path) {
            continue
        }
        $trimmed = $path.Trim()
        if (-not $trimmed) {
            continue
        }
        $normalized = $trimmed.TrimEnd('\')
        if ($seen.Add($normalized)) {
            $items += $trimmed
        }
    }
    $env:Path = ($items -join ';')
}

function Get-NpmCommand {
    foreach ($candidate in @(
        "C:\Program Files\Volta\npm.cmd",
        "C:\Program Files\Volta\npm.exe",
        (Join-Path $env:LOCALAPPDATA "Volta\bin\npm.cmd"),
        (Join-Path $env:LOCALAPPDATA "Volta\bin\npm.exe")
    )) {
        if ($candidate -and (Test-Path $candidate)) {
            return $candidate
        }
    }

    $command = Get-Command "npm.exe" -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $command = Get-Command "npm.cmd" -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    throw "No usable npm found. Install Node.js/npm or fix Volta."
}

function Invoke-Native {
    param([string]$Desc, [scriptblock]$Cmd)
    & $Cmd
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: $Desc (exit $LASTEXITCODE)" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}

Push-Location $ProjectRoot

Initialize-NodeToolchainPath
$NpmCommand = Get-NpmCommand

foreach ($requiredPath in @(".env", "prod/Dockerfile", "prod/docker-compose.yml", "config/llm.toml", "llm_about/_example/vocab.yaml", "llm_about/_example/identities.yaml", "docker/searxng/settings.yml")) {
    if (-not (Test-Path $requiredPath)) {
        Write-Host "Missing required file: $requiredPath" -ForegroundColor Red
        Pop-Location
        exit 1
    }
}

Write-Host "Building frontend..." -ForegroundColor Cyan
Push-Location "frontend"
Invoke-Native "npm install" { & $NpmCommand install }
Invoke-Native "npm build" { & $NpmCommand run build }
Pop-Location

Write-Host "Packing project..." -ForegroundColor Cyan
Invoke-Native "tar archive" {
    tar czf $TempArchive `
        --exclude='.git' `
        --exclude='.github' `
        --exclude='__pycache__' `
        --exclude='.venv' `
        --exclude='.vscode' `
        --exclude='data' `
        --exclude="$LocalPrivateWorkspace" `
        --exclude='prod/sendkey.env' `
        --exclude='prod/sendkey.env.example' `
        --exclude='prod/README.md' `
        --exclude='prod/llbot-qq' `
        --exclude='prod/llbot-data' `
        --exclude='frontend/node_modules' `
        --exclude='tests' `
        --exclude='test_*.py' `
        --exclude='scripts' `
        --exclude='requirements-dev.txt' `
        --exclude='.pytest-tmp-*' `
        --exclude='*.tar' `
        --exclude='*.tar.gz' `
        .
}
if (Test-Path $TiebaStateFile) {
    Write-Host "Packing Tieba storage state..." -ForegroundColor Cyan
    Invoke-Native "Tieba state archive" {
        tar czf $TiebaStateArchive $TiebaStateFile
    }
}
Pop-Location

if (-not (Test-Path $TempArchive)) {
    Write-Host "Archive was not created; aborting." -ForegroundColor Red
    exit 1
}

if ($LocalCheck) {
    $archiveInfo = Get-Item $TempArchive
    $archiveSizeMB = [Math]::Round($archiveInfo.Length / 1MB, 2)
    Write-Host "Local check complete. Archive size: ${archiveSizeMB} MB" -ForegroundColor Green
    Remove-Item -Force $TempArchive -ErrorAction SilentlyContinue
    Remove-Item -Force $TiebaStateArchive -ErrorAction SilentlyContinue
    exit 0
}

Write-Host "Uploading to server..." -ForegroundColor Cyan
Invoke-Native "scp archive" {
    scp @ScpArgs $TempArchive "${HostAlias}:/tmp/quickquip-deploy.tar.gz"
}
if (Test-Path $TiebaStateArchive) {
    Invoke-Native "scp Tieba state" {
        scp @ScpArgs $TiebaStateArchive "${HostAlias}:/tmp/quickquip-tieba-state.tar.gz"
    }
}
if (Test-Path $SendkeyEnvFile) {
    Write-Host "Uploading ops notification env..." -ForegroundColor DarkCyan
    Invoke-Native "scp sendkey env" {
        scp @ScpArgs $SendkeyEnvFile "${HostAlias}:/tmp/quickquip-sendkey.env"
    }
}
if (Test-Path $FontFile) {
    Write-Host "Uploading wordcloud font..." -ForegroundColor DarkCyan
    $fontInfo = Get-Item $FontFile
    $fontSizeMB = [Math]::Round($fontInfo.Length / 1MB, 2)
    Invoke-Native "ssh create font dir" {
        ssh @SshArgs $HostAlias "mkdir -p $RemoteDir/data/fonts"
    }
    Write-Host "Uploading font (${fontSizeMB} MB)..." -ForegroundColor DarkCyan
    Invoke-Native "scp font" {
        scp @ScpArgs $FontFile "${HostAlias}:${RemoteDir}/data/fonts/NotoSansSC-Regular.ttf"
    }
}

Write-Host "Extracting and rebuilding containers..." -ForegroundColor Cyan
$RemoteDeployScript = @'
set -eu
REMOTE_DIR="__REMOTE_DIR__"
NULL_DEVICE="/d""ev/null"
mkdir -p "$REMOTE_DIR"
cd "$REMOTE_DIR"

tar xzf /tmp/quickquip-deploy.tar.gz
rm -f "$REMOTE_DIR"/test_*.py "$REMOTE_DIR/requirements-dev.txt"
rm -rf "$REMOTE_DIR/tests" "$REMOTE_DIR/scripts"

if [ -f /tmp/quickquip-sendkey.env ]; then
    mkdir -p "$REMOTE_DIR/prod"
    install -m 600 /tmp/quickquip-sendkey.env "$REMOTE_DIR/prod/sendkey.env"
fi

if [ -f /tmp/quickquip-tieba-state.tar.gz ]; then
    mkdir -p "$REMOTE_DIR/data/tieba"
    tar xzf /tmp/quickquip-tieba-state.tar.gz -C "$REMOTE_DIR"
fi

sed -i 's/\r$//' "$REMOTE_DIR/.env" 2>"$NULL_DEVICE" || true
chmod 600 "$REMOTE_DIR/.env" 2>"$NULL_DEVICE" || true

if [ -f "$REMOTE_DIR/prod/sendkey.env" ]; then
    sed -i 's/\r$//' "$REMOTE_DIR/prod/sendkey.env" 2>"$NULL_DEVICE" || true
    chmod 600 "$REMOTE_DIR/prod/sendkey.env" 2>"$NULL_DEVICE" || true
fi

if [ -d "$REMOTE_DIR/prod/llbot-data" ]; then
    LLBOT_PYTHON=python3
    for candidate in "$REMOTE_DIR/prod/llbot-data/default_config.json" "$REMOTE_DIR"/prod/llbot-data/data/config_*.json; do
        if [ -e "$candidate" ] && [ ! -w "$candidate" ]; then
            LLBOT_PYTHON="sudo -n python3"
            break
        fi
    done
    $LLBOT_PYTHON - "$REMOTE_DIR" <<'PY'
import json
import sys
from pathlib import Path

remote_dir = Path(sys.argv[1])

def read_env_value(path: Path, key: str) -> str:
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return ""
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name == key:
            value = value.strip()
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
            return value
    return ""

token = read_env_value(remote_dir / ".env", "ONEBOT_ACCESS_TOKEN")
if not token:
    raise SystemExit(0)

paths = [remote_dir / "prod/llbot-data/default_config.json"]
paths.extend(sorted((remote_dir / "prod/llbot-data/data").glob("config_*.json")))
for path in paths:
    if not path.exists():
        continue
    data = json.loads(path.read_text(encoding="utf-8"))
    connect = data.setdefault("ob11", {}).setdefault("connect", [])
    while len(connect) <= 1:
        connect.append({})
    connect[1]["url"] = "ws://quickquip:8080/onebot/v11/ws/"
    connect[1]["token"] = token
    path.write_text(json.dumps(data, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")
    print(f"Synced LLBot OneBot reverse WebSocket config: {path}")
PY
fi

chmod 750 "$REMOTE_DIR" "$REMOTE_DIR/prod" 2>"$NULL_DEVICE" || true
if [ -f "$REMOTE_DIR/data/tieba/pool.json" ]; then
    sudo chown "$(id -u):$(id -g)" "$REMOTE_DIR/data/tieba/pool.json" 2>"$NULL_DEVICE" || true
fi

rm -f /tmp/quickquip-deploy.tar.gz /tmp/quickquip-tieba-state.tar.gz /tmp/quickquip-sendkey.env

cd "$REMOTE_DIR/prod"
docker compose --env-file ../.env config --quiet
docker compose --env-file ../.env build quickquip web-admin
docker compose --env-file ../.env up -d --remove-orphans searxng llbot quickquip web-admin
docker compose --env-file ../.env up -d --force-recreate quickquip web-admin
docker compose --env-file ../.env ps
docker builder prune --filter 'until=48h' --force
docker image prune -f
'@
$RemoteDeployScript = $RemoteDeployScript.Replace("__REMOTE_DIR__", $RemoteDir) -replace "`r`n", "`n"
Invoke-Native "ssh remote deploy" {
    $RemoteDeployScript | ssh @SshArgs $HostAlias "tr -d '\r' | bash -s"
}

Write-Host "Deploy complete." -ForegroundColor Green
Write-Host "QuickQuip logs: ssh $HostAlias 'cd $RemoteDir/prod && docker compose --env-file ../.env logs -f quickquip'" -ForegroundColor Yellow
Write-Host "Web Admin logs: ssh $HostAlias 'cd $RemoteDir/prod && docker compose --env-file ../.env logs -f web-admin'" -ForegroundColor Yellow
Write-Host "SearXNG logs: ssh $HostAlias 'cd $RemoteDir/prod && docker compose --env-file ../.env logs -f searxng'" -ForegroundColor Yellow

Remove-Item -Force $TempArchive -ErrorAction SilentlyContinue
Remove-Item -Force $TiebaStateArchive -ErrorAction SilentlyContinue
