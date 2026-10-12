# PowerShell SSH driver delegates to the same server-side CLI contract.
param(
    [ValidateSet('status','export','preview','import','apply','backup','restore')]
    [string]$Action = 'status',
    [string]$File = '', [int]$Revision = 0,
    [ValidatePattern('^(draft|published|[0-9]+)$')][string]$Source = 'published',
    [ValidatePattern('^[A-Za-z0-9_.@-]+$')][string]$HostAlias = 'quickquip-prod',
    [ValidatePattern('^/[A-Za-z0-9_./-]+$')][string]$RemoteDir = '/opt/QuickQuip',
    [ValidatePattern('^[A-Za-z0-9_.-]{1,128}$')][string]$RequestId = ''
)
$ErrorActionPreference = 'Stop'
if ($HostAlias.StartsWith('-') -or $RemoteDir -eq '/' -or $RemoteDir.Contains('..')) { throw 'Unsafe SSH target' }
if ($Action -in @('preview','import','apply') -and $Revision -lt 1) { throw 'Expected Revision required' }
if ($Action -in @('export','preview','import','backup','restore') -and -not $File) { throw 'File required' }
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
    }
    $server = @'
set -euo pipefail
Root=$1 Action=$2 TransferId=$3 Revision=$4 Source=$5 RequestId=$6
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
    status) "${Compose[@]}" exec -T web-admin "${CLI[@]}" status;;
    export) "${Compose[@]}" exec -T web-admin "${CLI[@]}" export --source "$Source" --output "$Path/output";;
    preview) "${Compose[@]}" exec -T web-admin "${CLI[@]}" import "$Path/input" --expected-revision "$Revision" --preview;;
    import) "${Compose[@]}" exec -T web-admin "${CLI[@]}" import "$Path/input" --expected-revision "$Revision";;
    apply) "${Compose[@]}" exec -T web-admin "${CLI[@]}" apply --expected-revision "$Revision" --request-id "$RequestId";;
    backup) "${Compose[@]}" exec -T web-admin "${CLI[@]}" backup "$Path/output";;
    restore)
        "${Compose[@]}" stop quickquip web-admin
        "${Compose[@]}" run --rm --no-deps web-admin "${CLI[@]}" restore --file "$Path/input" --services-stopped
        "${Compose[@]}" up -d --no-build quickquip web-admin
        ;;
esac
if [ -f "$Root/data/.llm-transfer-$TransferId/output" ]; then
    "${Compose[@]}" exec -T web-admin python -c \
        'import os,sys; os.chmod(sys.argv[1], 0o600); os.chown(sys.argv[1], int(sys.argv[2]), int(sys.argv[3]))' \
        "$Path/output" "$(id -u)" "$(id -g)"
fi
'@
    $server = $server.Replace("`r`n", "`n")
    $server | ssh $HostAlias bash -s -- $RemoteDir $Action $transferId $Revision $Source $RequestId
    if ($LASTEXITCODE -ne 0) { throw "Remote configuration action failed ($LASTEXITCODE)" }
    if ($Action -in @('export','backup')) {
        $destination = [IO.Path]::GetFullPath($File)
        $temporary = "$destination.$transferId.tmp"
        Invoke-Checked { scp "${HostAlias}:$transfer/output" $temporary }
        Move-Item -LiteralPath $temporary -Destination $destination -Force
    }
} finally {
    ssh $HostAlias "rm -rf '$transfer'" | Out-Null
}
