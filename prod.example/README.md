# QuickQuip Production Template

Copy this directory to the ignored `prod/` directory, then configure your SSH alias, compose topology and the project-root `.env`.

```bash
cp -r prod.example prod
```

```powershell
Copy-Item -Recurse prod.example prod
```

When `prod/` already exists, move it aside before copying. The drivers reject a nested `prod/prod.example` directory.

## Requirements

- Server: Linux, Bash, GNU coreutils/find, rsync, flock, Python >= 3.11.8, Docker and Docker Compose >= 2.27. The deployment user needs Docker access and write access to the deployment root. Root-owned LLBot configuration files use noninteractive sudo for shared-file snapshot, apply and restore; without permission the action stops before activation.
- Bash client: Bash, rsync, SSH/SCP, tar, Node.js and pnpm.
- PowerShell client: PowerShell 5.1 or 7, SSH/SCP, tar, Node.js and pnpm on PATH. The server materializes its archive with rsync.
- Initialize SSH host trust before unattended use. `quickquip-prod` is a placeholder SSH alias.
- Fill root `.env`, `config/llm.toml` and other enabled feature configuration. Set `QUICKQUIP_SEARXNG_BASE_URL` for the external search service.

## Commands

Both local drivers share `remote-deploy-v4.sh` and `deploy-state.py`.

| Action | Bash | PowerShell |
|---|---|---|
| Deploy | `bash prod/deploy-v4.sh` | `prod/deploy-v4.ps1` |
| Local preview | `bash prod/deploy-v4.sh -DryRun` | `prod/deploy-v4.ps1 -DryRun` |
| Status | `bash prod/deploy-v4.sh -Status` | `prod/deploy-v4.ps1 -Status` |
| Previous release | `bash prod/deploy-v4.sh -Rollback` | `prod/deploy-v4.ps1 -Rollback` |
| Explicit rollback | `bash prod/deploy-v4.sh -Rollback <id>` | `prod/deploy-v4.ps1 -Rollback -ReleaseId <id>` |
| Flat-layout migration and deploy | `bash prod/deploy-v4.sh -Migrate` | `prod/deploy-v4.ps1 -Migrate` |
| First deployment awaiting QQ login | `bash prod/deploy-v4.sh -SkipHealth` | `prod/deploy-v4.ps1 -SkipHealth` |

Shared parameters: `-HostAlias`, `-RemoteDir` (default `/opt/QuickQuip`), `-KeepReleases` (2..100, default 4). Remote paths use letters, digits, dot, slash, underscore or hyphen.

`-DryRun` builds the frontend locally and previews the upload; PowerShell creates and removes a temporary archive. It makes no remote connection. `-LocalCheck` is a compatibility alias. Combining preview with migration, rollback or status is rejected. `-SkipHealth` applies only to deployment/migration and explicitly marks the result unverified; manual rollback always requires health verification.

For first login, use `bash prod/check_bot_local.sh` or `prod/check_bot.ps1` after an explicit `-SkipHealth` deployment. Pass their `-Server` and `-RemoteDir` parameters for a custom target. The server worker is `prod/check_bot.sh`; `prod/cron_check_bot.sh` remains the cron entry.

## Layout and Transaction

```text
<root>/
  .env                       application credentials
  data/                      databases, logs, font and optional Tieba state
  prod/                      LLBot state, maintenance scripts, sendkey.env
  releases/<id>/             application, config, frontend and compose
  current -> releases/<id>
  previous -> releases/<id>
  .deploy/                   private staging, operation logs and exit status
```

`deploy-manifest.txt` lists application paths. Listed directories are recursive: review their contents before deployment. Root `.env`, maintenance scripts and optional `prod/sendkey.env`, font and `data/tieba/storage_state.json` are uploaded separately to private staging. LLBot login directories are never uploaded. For a test server, prepare an isolated checkout without real credentials or Tieba session files.

Each operation has a UTC timestamp plus random suffix. Uploads enter an exclusive private directory; live files are modified only under the server deployment lock. The candidate compose is validated against the staged environment and its image built before shared files are applied. Unchanged application files use rsync hardlinks; release roots and transaction directories restrict access to the deployment user. Web Admin configuration writes use atomic file replacement, preserving older hardlinked content.

Before activation, the server snapshots shared files that it will replace, including existing LLBot WebSocket configuration. It applies the candidate environment, switches `current`, and recreates application containers once. The health gate checks all three services, the bot connection log and Web Admin HTTP inside its container. SSH disconnects do not stop the detached transaction; drivers reconnect to its log.

Successful operations remove private staging and rollback copies, retaining `.deploy/<id>.log` and `.exit`. Interrupted uploads can leave staging directories; inspect operation status before manually removing these. Failed recovery retains its private backup and returns exit code 2. The requested action still returns nonzero when automatic recovery succeeds.

## Migration and Recovery

`-Migrate` snapshots the server's existing application files and pins actual running images of `llbot`, `quickquip` and `web-admin` as a baseline, then deploys the local candidate. Flat files remain in place so existing bind mounts stay valid during preparation. Custom services or unsupported external bind mounts require an explicit migration design; the script stops before activation. Baselines are not automatically collected.

Automatic recovery restores pre-operation shared files, links and containers, then verifies health. Manual rollback selects an existing release and its local images, retains the current root `.env` and runtime data, and verifies health. Missing rollback images are never pulled or rebuilt. Do not prune retained release tags manually.

Database migrations and external effects are outside filesystem rollback. Check upgrade notes and prepare a separate data backup when required; code rollback can require coordinated data restore. Server-side configuration edits belong to their release; subsequent deployments use local candidate configuration.

Retention removes older successfully deployed release directories and application images, protecting `current`, `previous` and migration baselines. Failed candidates and operation logs remain for manual inspection. Root `.env` remains the application credential source; transaction copies are private and transient.

`deploy-v4-bak.sh` and `deploy-v4-bak.ps1` preserve the archived flat-layout drivers for inspection and controlled legacy tests. They refuse targets with a release directory or a current link. Use `deploy-v4` for current deployments.

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

Application prerequisites and platform notes: [deployment guide](../docs/admin/deployment.md).
