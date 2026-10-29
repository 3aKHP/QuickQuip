# QuickQuip Production Template

The tracked deployment drivers publish Docker Compose services to a remote Linux host over SSH. Containers built from source or using source bind mounts follow the same Docker runtime. See [installation and deployment modes](../../docs/admin/installation.md) for the local/remote and source/Docker definitions and installation routes.

Run the drivers from the project root. Prepare the private Compose configuration using [prod.example](../../prod.example/README.md); the programs in this directory update with the repository.

```bash
bash scripts/deploy/deploy-v4.sh --help
```

## Requirements

- Server: Linux, Bash, GNU coreutils/find, rsync, flock, Python >= 3.11.8, Docker and Docker Compose >= 2.27. The deployment user needs Docker access and write access to the deployment root. Root-owned LLBot configuration files use noninteractive sudo for shared-file snapshot, apply and restore; without permission the action stops before activation.
- Bash client: Bash, rsync, SSH/SCP, tar, Node.js, pnpm and the project Python environment.
- PowerShell client: PowerShell 5.1 or 7, SSH/SCP, tar, Node.js, pnpm and the project Python environment on PATH. The server materializes the release archive with `deploy-state.py` (Python tarfile); rsync on the server is used for precondition checks only.
- Initialize SSH host trust before unattended use. `quickquip-prod` is a placeholder SSH alias.
- Fill root `.env` and enabled feature files, including personas when using LLM. Set `QUICKQUIP_SEARXNG_BASE_URL` for the external search service. The driver initializes the server configuration database before activation; an existing server legacy TOML is migrated once. Configure channels through Web after Bot and Web are running.

## SSH Connection

Deployment and configuration synchronization use QUICKQUIP_DEPLOY_SSH_HOST and QUICKQUIP_DEPLOY_REMOTE_DIR from the real root `.env`, with explicit command options taking precedence. The SSH host value names an entry in your local SSH configuration. Open `~/.ssh/config` on Linux/macOS or `%USERPROFILE%\.ssh\config` on Windows in a text editor; create the file if needed. Add an entry, replacing the example IP and user with your server details:

```sshconfig
Host quickquip-prod
    HostName 192.0.2.10
    User deploy
    Port 22
```

In a local terminal, run `ssh quickquip-prod` to verify the target and complete the first host-key check. Configure your SSH public key so subsequent connections can run unattended. Once you see the server shell, run `exit` to return to your computer. Use this alias with `--host-alias quickquip-prod` (PowerShell: `-HostAlias quickquip-prod`).

First application setup, including a standalone search-service route and the required environment values, is in the [deployment guide](../../docs/admin/deployment.md#3-准备生产运维目录和环境变量). Start Bot and Web before using the [first LLM setup steps](../../docs/admin/llm-configuration.md#首次启用-llm).

## Configuration Synchronization

Set `QUICKQUIP_DEPLOY_LOCATION=cloud` and `QUICKQUIP_DEPLOY_RUNTIME=docker` in the real root `.env` on both ends. Servers using `data/llm_config.db` require `bash scripts/deploy/deploy-v4.sh --migrate-storage`; this retains server configuration and disables synchronization for the migration. For an already migrated server receiving qqsync for the first time, use `--config-sync off`; a new server additionally needs `--env local`. Follow the [storage migration steps](../../docs/admin/storage-migration.md) before the first synchronization.

Choose the first source through the command direction:

```bash
qqsync refresh --direction pull
qqsync pull
qqconf unpack
```

`pull` brings published server configuration into local real files; `push` deploys local real configuration. Subsequent operations merge independent field edits and report conflicts. Root `.env`, Compose and notification settings share the same configuration plan. See the [qqsync guide](../../docs/admin/config-sync.md) for the managed scope, drafts and conflict choices.

Normal code deployment defaults to `--config-sync push`. `pull` receives server changes before packaging; `off` retains server configuration. `--plan` previews without building or modifying configuration. The independent `--env` option is available with `off` for bootstrap or maintenance; ordinary synchronization already includes root `.env`. PowerShell uses `-ConfigSync`, `-Plan`, and `-EnvSource`.

The deployment transaction stages the reconciled configuration and environment before image validation, publishes while consumers are stopped, then switches and starts the new release. Repeating the same command continues or recovers interrupted work using its recorded destination. Standalone qqsync preserves each service's original running/stopped state; a code deployment starts the new version and checks its health.

## Commands

Both local drivers use the transaction worker and state program in `server/`. Private `prod/` contains configuration and protocol login assets.

| Action | Bash | PowerShell |
|---|---|---|
| Deploy with configuration push | `bash scripts/deploy/deploy-v4.sh` | `scripts/deploy/deploy-v4.ps1` |
| Local preview | `bash scripts/deploy/deploy-v4.sh --dry-run` | `scripts/deploy/deploy-v4.ps1 -DryRun` |
| Status | `bash scripts/deploy/deploy-v4.sh --status` | `scripts/deploy/deploy-v4.ps1 -Status` |
| Previous release | `bash scripts/deploy/deploy-v4.sh --rollback` | `scripts/deploy/deploy-v4.ps1 -Rollback` |
| Explicit rollback | `bash scripts/deploy/deploy-v4.sh --rollback <id>` | `scripts/deploy/deploy-v4.ps1 -Rollback -ReleaseId <id>` |
| Flat-layout migration and deploy | `bash scripts/deploy/deploy-v4.sh --migrate --config-sync off` | `scripts/deploy/deploy-v4.ps1 -Migrate -ConfigSync off` |
| First deployment awaiting QQ login | `bash scripts/deploy/deploy-v4.sh --config-sync off --env local --skip-health` | `scripts/deploy/deploy-v4.ps1 -ConfigSync off -EnvSource local -SkipHealth` |

Shared parameters: `--host-alias`, `--remote-dir` (default `/opt/QuickQuip`), `--keep-releases` (2..100, default 4); the PowerShell driver takes the matching single-dash forms (`-HostAlias`, `-RemoteDir`, `-KeepReleases`). Remote paths use letters, digits, dot, slash, underscore or hyphen. Run `bash scripts/deploy/deploy-v4.sh --help` for the full interface.

`--dry-run` builds the frontend locally and previews the upload; PowerShell creates and removes a temporary archive. It makes no remote connection. `--local-check` (PowerShell: `-LocalCheck`) is a compatibility alias. Combining preview with migration, rollback or status is rejected. `--skip-health` requires `--config-sync off` and applies only to deployment/migration and explicitly marks the result unverified; manual rollback always requires health verification.

Every release carries a version identity built from the deployed `pyproject.toml` version plus a timestamp captured on the server when the image build finishes (for example `1.15.3-dev.2+build.20260909.065235`); it is echoed in the `image built` and `release complete` transaction log lines. If you maintain your own private ops-trail tooling, `remote-deploy-v4.sh` marks the spot where `$VersionId` is available for you to record it.

For first login, use `bash scripts/ops/check_bot_local.sh` or `scripts/ops/check_bot.ps1` after an explicit `--skip-health` deployment. Pass their `-Server` and `-RemoteDir` parameters for a custom target. The server worker is `scripts/ops/check_bot.sh`; `scripts/ops/cron_check_bot.sh` remains the cron entry.

`scripts/ops/host_metrics_collector.py` optionally supplies host process counts, full disk usage and temperatures for the host-healthcheck Skill. Install its cron entry from the file header. Each run atomically writes `<root>/data/host_metrics.json`, which the container reads through the existing read-only `data/` bind mount.

### Shared Skill Catalog

Skills live at `<root>/skills` beside `data/`. The bot mounts the catalog read-only and Web Admin read-write, so Web-installed Skills survive container recreation and later deployments.

The drivers upload the local `skills/` directory and add missing files to the shared catalog. Existing files, including Web Admin installs and edits, are preserved; updates and removals go through the Web Admin Skill page or manual server maintenance. On first use, the server seeds an absent catalog from the previous current release, or creates an empty directory, before adding the uploaded files.

The catalog belongs to the deployment user. Web-installed files can be root-owned because the Web Admin container runs as root. When a merge requires access to those entries, it retries with noninteractive sudo and restores ownership of the whole catalog to the deployment user. If sudo is unavailable, deployment stops and prints the manual `chown` command to run.

## Layout and Transaction

```text
<root>/
  .env                       application credentials
  config/managed/            shared configuration database and recurring schedules
  data/                      execution/business databases, logs, font and optional Tieba state
  skills/                    shared skill catalog (bot read-only, Web Admin read-write)
  prod/                      LLBot state, Compose configuration, sendkey.env
  scripts/ops/               managed server inspection and metrics programs
  releases/<id>/             application, config, frontend and compose
  current -> releases/<id>
  previous -> releases/<id>
  .deploy/                   private staging, operation logs and exit status
```

`deploy-manifest.txt` lists application paths. Listed directories are recursive: review their contents before deployment. The selected root `.env`, maintenance scripts and optional `prod/sendkey.env`, font and `data/tieba/storage_state.json` are uploaded separately to private staging. LLBot login directories are never uploaded. For a test server, prepare an isolated checkout without real credentials or Tieba session files.

Each operation has a UTC timestamp plus random suffix. Uploads enter an exclusive private directory; live files are modified only under the server deployment lock. The candidate compose is validated against the staged environment and its image built before shared files are applied. Unchanged application files use rsync hardlinks; release roots and transaction directories restrict access to the deployment user. Web Admin configuration writes use atomic file replacement, preserving older hardlinked content.

Before activation, the server snapshots shared files that it will replace, including existing LLBot WebSocket configuration. It applies the candidate environment, switches `current`, and recreates application containers once. The health gate checks all three services, the bot connection log, Web Admin HTTP, configuration schema and the bot heartbeat/load acknowledgement inside its container. The bot core must be ready with an available conversation store. Remote models and MCP servers can remain unavailable independently. SSH disconnects do not stop the detached transaction; drivers reconnect to its log.

Successful operations remove private staging and rollback copies, retaining `.deploy/<id>.log`, `.exit`, and the synchronization deployment `.transaction.json` recovery record. Interrupted uploads can leave staging directories; inspect operation status before manually removing these. Failed recovery retains its private backup and returns exit code 2. The requested action still returns nonzero when automatic recovery succeeds.

## Migration and Recovery

Production builds use the tracked `docker/Dockerfile.prod`. Existing Compose files may retain `build.dockerfile: prod/Dockerfile`: deployment creates that compatibility build file inside each candidate release from the tracked source, including when configuration is pulled from the server. The private deployment-root `prod/` keeps its configuration. New Compose configurations use `docker/Dockerfile.prod` directly.

`--migrate` snapshots the server's existing application files and pins actual running images of `llbot`, `quickquip` and `web-admin` as a baseline, then deploys the local candidate. Flat files remain in place so existing bind mounts stay valid during preparation. Custom services or unsupported external bind mounts require an explicit migration design; the script stops before activation. Baselines are not automatically collected.

Automatic recovery restores pre-operation shared files, links and containers, then verifies health. Manual rollback selects an existing release and its local images, retains the current root `.env`, runtime data and the shared `skills/` catalog (applying the same non-destructive merge from the rollback target's `skills/` when its compose consumes the shared catalog), and verifies health. Historical releases whose compose mounts a release-local `skills/` keep using that frozen copy when rolled back. Missing rollback images are never pulled or rebuilt. Do not prune retained release tags manually.

Filesystem rollback restores deployment files and containers. Database migrations and external effects require their own recovery steps; check upgrade notes and prepare the necessary data backups before deployment.

The configuration database and recurring schedules are shared in `config/managed/`; publication and task state are shared in `data/config_runtime.db`. Normal uploads exclude local database files and legacy LLM TOML. First migration uses server-side configuration after a successful candidate image build. Managed configuration assets follow the synchronization result. With synchronization off, the candidate retains server configuration after pausing its writers.

Reading root-owned migration assets uses noninteractive sudo when required, and copied assets belong to the deployment user. Copy or discovery failure stops activation; existing candidate assets retain priority.

Existing mixed-storage installations use `bash scripts/deploy/deploy-v4.sh --migrate-storage` (PowerShell: `-MigrateStorage`). This retains server configuration, pauses Bot and Web after the candidate image builds, separates configuration and execution storage, then verifies startup. An incomplete migration restores its backup; a completed migration is reversed on startup failure while preserving subsequent business records and task progress. Schema 1/2 configuration databases first need the schema-3 upgrade using the corresponding older application. See [storage migration](../../docs/admin/storage-migration.md).
Retention removes older successfully deployed release directories and application images, protecting `current`, `previous` and migration baselines. Failed candidates and operation logs remain for manual inspection. Root `.env` remains the application credential source; transaction copies are private and transient.

`legacy/deploy-v4-bak.sh` and `legacy/deploy-v4-bak.ps1` preserve the archived flat-layout drivers for inspection and controlled legacy tests. They refuse targets with a release directory or a current link. Use `deploy-v4` for current deployments.

## Manual Compose Access

On a release-layout server, export the root and release identity:

```bash
export QUICKQUIP_ROOT=/opt/QuickQuip
export QUICKQUIP_ENV_FILE="$QUICKQUIP_ROOT/.env"
export QUICKQUIP_RELEASE="$(basename "$(readlink "$QUICKQUIP_ROOT/current")")"
cd "$QUICKQUIP_ROOT/current/prod"
docker compose --env-file "$QUICKQUIP_ENV_FILE" logs -f quickquip
```

For manual flat-layout installation, build the frontend, then run `docker compose --env-file ../.env build quickquip` and `docker compose --env-file ../.env up -d` from `prod/`. Both application services use the same image.

Application prerequisites and platform notes: [deployment guide](../../docs/admin/deployment.md).

## LLM Configuration Operations

`legacy/config-v1.sh` and `legacy/config-v1.ps1` run the same configuration CLI inside the active release's Web Admin container over SSH. Configure the host alias and deployment root when calling them. These commands keep secrets in the root `.env`, exchange JSON and check the expected draft revision.

```bash
bash scripts/deploy/legacy/config-v1.sh status
bash scripts/deploy/legacy/config-v1.sh export --source published --file llm-export.json
bash scripts/deploy/legacy/config-v1.sh preview --file llm-export.json --revision 1
bash scripts/deploy/legacy/config-v1.sh import --file llm-export.json --revision 1
bash scripts/deploy/legacy/config-v1.sh apply --revision 2
bash scripts/deploy/legacy/config-v1.sh backup --file llm-config-backup.db
bash scripts/deploy/legacy/config-v1.sh restore --file llm-config-backup.db
```

PowerShell equivalents use `-Action`, `-File`, `-Revision`, `-Source`, `-HostAlias` and `-RemoteDir`. Backup saves `llm-config-backup.db` together with `llm-config-backup.db.runtime.db`; keep both files in the same directory. Restore checks that both local files exist, stops bot and Web, backs up the current databases, restores and restarts services after successful recovery. A restore failure leaves services stopped for inspection. Import saves a draft; apply submits a separate bot-owned operation.

Before rollback to 1.16.1, use the migration backup TOML and independent assets. Back up the configuration, conversation and Trace databases before changing versions. The new configuration database remains available for a subsequent upgrade; configuration changes made after migration have no reverse TOML export. After running older code, stop bot and Web and reset the conversation Session identity columns before upgrading again; preserve a current conversation backup first. The database paths and maintenance SQL are in [rollback and re-upgrade](../../docs/admin/llm-configuration.md#回退旧版本后再次升级).

Local editing uses [qqconf](../../docs/admin/config-workspace.md). With cloud deployment selected, `pack` writes local real configuration for qqsync or deploy-v4 to send. With local deployment selected, `pack` writes `.config-staging/` and `qqsync push` installs it. The workspace remains owned by qqconf.

## Private deployment hook

A deployment-specific integration can live in `prod/hooks/deployment.sh`. The client uploads it as a private shared asset when present. After successful activation or rollback, the worker calls it as `bash deployment.sh <action> <version> <release>` under the deployment user. After 30 seconds it requests termination, then forcibly stops the hook after a further 5 seconds if needed. Hook failure is logged after the release outcome has been established.

Bash `--message` / `-m` and PowerShell `-Message` carry an optional UTF-8 note in the base64-encoded `DEPLOY_NOTE_B64` environment variable. The hook may decode it for its own audit integration. This private program is maintained by the deployer; qqconf/qqsync do not synchronize its body.
