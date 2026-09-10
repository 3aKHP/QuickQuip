# Local release driver. Shares the remote transaction with deploy-v4.sh.
param(
    [Alias("LocalCheck")][switch]$DryRun,
    [switch]$Status,
    [switch]$Rollback,
    [string]$ReleaseId = "",
    [switch]$Migrate,
    [switch]$SkipHealth,
    [string]$HostAlias = "quickquip-prod",
    [string]$RemoteDir = "/opt/QuickQuip",
    [int]$KeepReleases = 4
)
$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
function Invoke-Native([string]$Description, [scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "$Description (exit $LASTEXITCODE)" }
}
$Mode = "deploy"
if ($Status) { $Mode = "status" }
if ($Rollback) { $Mode = "rollback" }
if ($Migrate) { $Mode = "migrate" }
if (([int]$Status.IsPresent + [int]$Rollback.IsPresent + [int]$Migrate.IsPresent) -gt 1) { throw "Choose only one action" }
if ($DryRun -and ($Mode -ne "deploy" -or $SkipHealth)) { throw "DryRun supports deployment preview only" }
if ($SkipHealth -and $Mode -notin @("deploy", "migrate")) { throw "SkipHealth supports deploy/migrate only" }
if ($ReleaseId -and -not $Rollback) { throw "ReleaseId requires Rollback" }
if ($ReleaseId -and $ReleaseId -cnotmatch '^[0-9]{8}-[0-9]{6}(-[a-f0-9]{12})?(-baseline)?$') { throw "Invalid release id" }
if ($RemoteDir -cnotmatch '^/[a-zA-Z0-9_./-]+$' -or $RemoteDir -eq '/' -or $RemoteDir.Contains('/../')) { throw "Invalid absolute deployment root" }
if ($HostAlias -cnotmatch '^[a-zA-Z0-9_][a-zA-Z0-9_.@-]*$') { throw "Invalid SSH alias" }
if ($KeepReleases -lt 2 -or $KeepReleases -gt 100) { throw "KeepReleases must be 2..100" }
$Version = ""
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
$SshArgs = @('-o', 'StrictHostKeyChecking=accept-new', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3')
$Id = [DateTime]::UtcNow.ToString('yyyyMMdd-HHmmss') + '-' + [Guid]::NewGuid().ToString('N').Substring(0, 12)
$Incoming = "$RemoteDir/.deploy/incoming/$Id"
$Temp = Join-Path ([System.IO.Path]::GetTempPath()) "quickquip-$Id"
Push-Location $ProjectRoot
try {
    if (Test-Path -PathType Container 'prod/prod.example') { throw 'Nested prod/prod.example; initialize prod again' }
    foreach ($file in @('remote-deploy-v4.sh', 'deploy-state.py')) {
        if (-not (Test-Path (Join-Path $ScriptDir $file))) { throw "Missing $file" }
    }
    if ($Mode -in @('deploy', 'migrate')) {
        if (-not (Test-Path '.env')) { throw 'Root .env missing' }
        $versionLine = Select-String -Path 'pyproject.toml' -Pattern '^version = "(.+)"$' | Select-Object -First 1
        if (-not $versionLine) { throw 'Cannot parse project version from pyproject.toml' }
        $Version = $versionLine.Matches[0].Groups[1].Value
        if ($Version -cnotmatch '^[0-9]+(\.[0-9]+){2}([-+][0-9A-Za-z.]+)*$') { throw "Invalid project version: $Version" }
        $pnpm = Get-Command pnpm.cmd, pnpm.exe, pnpm -ErrorAction SilentlyContinue | Select-Object -First 1
        if (-not $pnpm) { throw 'Install pnpm and put it on PATH' }
        Push-Location frontend
        try {
            Invoke-Native 'frontend dependencies' { & $pnpm.Source install --frozen-lockfile }
            Invoke-Native 'frontend build' { & $pnpm.Source build }
        } finally { Pop-Location }
        $entries = @(Get-Content (Join-Path $ScriptDir 'deploy-manifest.txt'))
        foreach ($item in $entries) {
            if ($item -cnotmatch '^[a-zA-Z0-9_./-]+$' -or $item.StartsWith('/') -or $item.Contains('..')) { throw 'Invalid manifest entry' }
            if (-not (Test-Path $item)) { throw "Missing manifest entry: $item" }
        }
        New-Item -ItemType Directory $Temp | Out-Null
        $List = Join-Path $Temp 'manifest.txt'
        $Archive = Join-Path $Temp 'release.tar.gz'
        [System.IO.File]::WriteAllText($List, (($entries -join "`n") + "`n"), [System.Text.UTF8Encoding]::new($false))
        Invoke-Native 'release archive' { tar --exclude=__pycache__ --exclude='*.pyc' -czf $Archive -T $List }
        if ($DryRun) {
            Invoke-Native 'archive preview' { tar -tzf $Archive }
            Write-Host 'Preview complete; frontend built locally, temporary archive removed, no remote connection or upload.'
            Write-Host "Version identity for this release: v$Version+build.<server build time>"
            return
        }
    }
    Invoke-Native 'remote prerequisites and exclusive staging' {
        ssh @SshArgs $HostAlias "command -v rsync >/dev/null && command -v flock >/dev/null && docker compose version >/dev/null && umask 077 && mkdir -p '$RemoteDir/.deploy/incoming' && chmod 700 '$RemoteDir/.deploy' '$RemoteDir/.deploy/incoming' && mkdir '$Incoming'"
    }
    Invoke-Native 'runner upload' {
        scp @SshArgs (Join-Path $ScriptDir 'remote-deploy-v4.sh') (Join-Path $ScriptDir 'deploy-state.py') "${HostAlias}:$Incoming/"
    }
    if ($Mode -in @('deploy', 'migrate')) {
        Invoke-Native 'archive upload' { scp @SshArgs $Archive "${HostAlias}:$Incoming/release.tar.gz" }
        $shared = @('.env', 'prod/check_bot.sh', 'prod/cron_check_bot.sh')
        foreach ($item in @('prod/sendkey.env', 'data/fonts/NotoSansSC-Regular.ttf', 'data/tieba/storage_state.json')) {
            if (Test-Path $item) { $shared += $item }
        }
        foreach ($item in $shared) {
            $parent = if ($item.Contains('/')) { $item.Substring(0, $item.LastIndexOf('/')) } else { '' }
            Invoke-Native 'private shared staging' { ssh @SshArgs $HostAlias "umask 077; mkdir -p '$Incoming/shared/$parent'" }
            Invoke-Native 'shared upload' { scp @SshArgs $item "${HostAlias}:$Incoming/shared/$item" }
        }
    }
    $skip = if ($SkipHealth) { '1' } else { '0' }
    Invoke-Native 'launch (if uncertain, inspect operation log before retrying)' {
        ssh @SshArgs $HostAlias "DEPLOY_VERSION='$Version' DETACH=1 SKIP_HEALTH=$skip bash '$Incoming/remote-deploy-v4.sh' '$RemoteDir' '$Id' '$KeepReleases' '$Mode' '$ReleaseId'"
    }
    $Log = "$RemoteDir/.deploy/$Id.log"
    $ExitFile = "$RemoteDir/.deploy/$Id.exit"
    $attempts = 0
    while ($true) {
        ssh @SshArgs $HostAlias "while [ ! -f '$ExitFile' ]; do sleep 1; done & watcher=`$!; tail -n +1 -f --pid=`$watcher '$Log'; wait `$watcher"
        if ($LASTEXITCODE -eq 0) { break }
        $attempts++
        if ($attempts -gt 20) { throw "Connection lost; remote action may continue: $Log" }
        Start-Sleep -Seconds 5
    }
    $code = ssh @SshArgs $HostAlias "cat '$ExitFile'"
    if ($LASTEXITCODE -ne 0 -or "$code".Trim() -ne '0') { throw "Remote action failed (exit $code): $Log" }
    Write-Host "$Mode complete. Status: prod/deploy-v4.ps1 -Status -HostAlias $HostAlias -RemoteDir $RemoteDir"
} finally {
    if (Test-Path $Temp) { Remove-Item -Recurse -Force $Temp }
    Pop-Location
}
