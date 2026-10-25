# PowerShell SSH driver delegates to the same server-side CLI contract.
param(
    [ValidateSet('status','export','preview','import','apply','backup','restore','sync')]
    [string]$Action = 'status',
    [string]$File = '', [int]$Revision = 0,
    [switch]$Wait, [int]$Timeout = 150,
    [ValidatePattern('^[a-f0-9]{32}$')][string]$Operation = '',
    [string]$SyncAction = 'sync',
    [ValidateSet('auto','push','pull')][string]$Mode = 'auto',
    [ValidateSet('local','remote')][string]$From = '',
    [switch]$Plan, [switch]$Overwrite, [switch]$ServicesStopped,
    [ValidatePattern('^(draft|published|[0-9]+)$')][string]$Source = 'published',
    [ValidatePattern('^[A-Za-z0-9_.@-]+$')][string]$HostAlias = 'quickquip-prod',
    [ValidatePattern('^/[A-Za-z0-9_./-]+$')][string]$RemoteDir = '/opt/QuickQuip',
    [ValidatePattern('^[A-Za-z0-9_.-]{1,128}$')][string]$RequestId = ''
)
$ErrorActionPreference = 'Stop'
if ($Action -eq 'sync') {
    if ($SyncAction -eq 'init' -and -not $From) { throw 'Initialization requires explicit From local or remote' }
    $SyncTimeout = if ($PSBoundParameters.ContainsKey('Timeout')) { $Timeout } else { 240 }
    Push-Location (Split-Path $PSScriptRoot)
    try {
        $python = @('.venv/Scripts/python.exe', '.venv/bin/python', 'python3', 'python') |
            Where-Object { Get-Command $_ -ErrorAction SilentlyContinue } | Select-Object -First 1
        if (-not $python) { throw 'Install the local Python environment first' }
        $syncArgs = @('-m', 'quickquip.config_sync.cli', $SyncAction,
            '--host-alias', $HostAlias, '--remote-dir', $RemoteDir, '--mode', $Mode,
            '--timeout', "$SyncTimeout")
        if ($SyncAction -eq 'init') { $syncArgs += @('--from', $From) }
        if ($Plan) { $syncArgs += '--plan' }
        if ($Overwrite) { $syncArgs += '--overwrite' }
        if ($ServicesStopped) { $syncArgs += '--services-stopped' }
        if ($Operation) { $syncArgs += @('--operation', $Operation) }
        & $python @syncArgs
        if ($LASTEXITCODE -ne 0) { throw 'Configuration synchronization failed' }
    } finally { Pop-Location }
    return
}
if ($Timeout -le 0) { throw 'Timeout must be positive' }
if ($HostAlias.StartsWith('-') -or $RemoteDir -eq '/' -or $RemoteDir.Contains('..')) { throw 'Unsafe SSH target' }
if ($Action -in @('preview','import','apply') -and $Revision -lt 1) { throw 'Expected Revision required' }
if ($Action -in @('export','preview','import','backup','restore') -and -not $File) { throw 'File required' }
if ($Action -eq 'restore' -and -not (Test-Path -LiteralPath "$File.runtime.db" -PathType Leaf)) {
    throw 'Restore requires the backup and its .runtime.db file'
}
$transferId = [guid]::NewGuid().ToString('N')
if (-not $RequestId) { $RequestId = $transferId }
$transfer = "$RemoteDir/data/.llm-transfer-$transferId"
function Invoke-Checked([scriptblock]$Command) {
    & $Command
    if ($LASTEXITCODE -ne 0) { throw "Remote configuration command failed ($LASTEXITCODE)" }
}
Invoke-Checked { ssh $HostAlias "umask 077; mkdir -p '$RemoteDir/data'; mkdir '$transfer'" }
try {
    if ($Action -in @('preview','import','restore')) {
        $localFile = (Resolve-Path -LiteralPath $File).Path
        Invoke-Checked { scp $localFile "${HostAlias}:$transfer/input" }
        Invoke-Checked { ssh $HostAlias "chmod 600 '$transfer/input'" }
        if ($Action -eq 'restore') {
            Invoke-Checked { scp "$localFile.runtime.db" "${HostAlias}:$transfer/input.runtime.db" }
            Invoke-Checked { ssh $HostAlias "chmod 600 '$transfer/input.runtime.db'" }
        }
    }
    $server = @'
set -euo pipefail
Root=$1 Action=$2 TransferId=$3 Revision=$4 Source=$5 RequestId=$6
Wait=$7 Timeout=$8 Operation=$9
export QUICKQUIP_ROOT="$Root" QUICKQUIP_ENV_FILE="$Root/.env"
if [ -L "$Root/current" ]; then
    QUICKQUIP_RELEASE="$(basename "$(readlink "$Root/current")")"
    export QUICKQUIP_RELEASE
    cd "$Root/current/prod"
else
    cd "$Root/prod"
fi
Compose=(docker compose --env-file "$Root/.env")
CLI=(python -m quickquip.llm.config_cli)
Path="/app/data/.llm-transfer-$TransferId"
case "$Action" in
    status) Extra=(); [ -z "$Operation" ] || Extra=(--operation "$Operation"); "${Compose[@]}" exec -T web-admin "${CLI[@]}" status "${Extra[@]}";;
    export) "${Compose[@]}" exec -T web-admin "${CLI[@]}" export --source "$Source" --output "$Path/output";;
    preview) "${Compose[@]}" exec -T web-admin "${CLI[@]}" import "$Path/input" --expected-revision "$Revision" --preview;;
    import) "${Compose[@]}" exec -T web-admin "${CLI[@]}" import "$Path/input" --expected-revision "$Revision";;
    apply) Extra=(); [ "$Wait" = 0 ] || Extra=(--wait --timeout "$Timeout"); "${Compose[@]}" exec -T web-admin "${CLI[@]}" apply --expected-revision "$Revision" --request-id "$RequestId" "${Extra[@]}";;
    backup) "${Compose[@]}" exec -T web-admin "${CLI[@]}" backup "$Path/output";;
    restore)
        umask 077
        mkdir -p "$Root/.deploy"
        exec 9>"$Root/.deploy/lock"
        flock -n 9 || { echo 'Another deployment operation is active' >&2; exit 1; }
        "${Compose[@]}" run --rm --no-deps web-admin python -c \
            'from pathlib import Path; import sys; sys.exit(1 if Path("/app/data/config-sync/maintenance.json").exists() else 0)' \
            || { echo 'Finish configuration synchronization before restoring a database' >&2; exit 1; }
        "${Compose[@]}" stop quickquip web-admin
        "${Compose[@]}" run --rm --no-deps web-admin "${CLI[@]}" restore --file "$Path/input" --services-stopped
        "${Compose[@]}" up -d --no-build quickquip web-admin
        ;;
esac
for name in output output.runtime.db; do
    if [ -f "$Root/data/.llm-transfer-$TransferId/$name" ]; then
        "${Compose[@]}" exec -T web-admin python -c \
            'import os,sys; os.chmod(sys.argv[1], 0o600); os.chown(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]))' \
            "$Path/$name" "$(id -u)" "$(id -g)"
    fi
done
'@
    $server = $server.Replace("`r`n", "`n")
    $server | ssh $HostAlias bash -s -- $RemoteDir $Action $transferId $Revision $Source $RequestId ([int][bool]$Wait) $Timeout "'$Operation'"
    if ($LASTEXITCODE -ne 0) { throw "Remote configuration action failed ($LASTEXITCODE)" }
    if ($Action -in @('export','backup')) {
        $destination = [IO.Path]::GetFullPath($File)
        $temporary = "$destination.$transferId.tmp"
        Invoke-Checked { scp "${HostAlias}:$transfer/output" $temporary }
        if ($Action -eq 'backup') {
            $runtimeTemporary = "$destination.runtime.db.$transferId.tmp"
            Invoke-Checked { scp "${HostAlias}:$transfer/output.runtime.db" $runtimeTemporary }
            Move-Item -LiteralPath $runtimeTemporary -Destination "$destination.runtime.db" -Force
        }
        Move-Item -LiteralPath $temporary -Destination $destination -Force
    }
} finally {
    ssh $HostAlias "rm -rf '$transfer'" | Out-Null
}
