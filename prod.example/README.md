# QuickQuip Production Template

This directory is the tracked template for the private `prod/` directory.

Copy it before first use (Windows or Linux):

```powershell
# Windows (PowerShell)
Copy-Item -Recurse prod.example prod
```

```bash
# Linux / macOS
cp -r prod.example prod
```

Then edit only files under `prod/` and the project root `.env`.

- `.env` at the repository root is the only QuickQuip application secret/config source.
- `QUICKQUIP_SEARXNG_BASE_URL` may be set in `.env` if the containers should use a search service outside this compose project.
- `prod/sendkey.env` is optional and used only by maintenance scripts.
- `prod/` is ignored by git and may contain production-only operational state.
- `quickquip-prod` in the helper scripts is a placeholder SSH host alias; change it under `prod/` before use.

Local helper scripts (run from the project root on your machine; both variants SSH into the server and share the same server-side workers):

| Action | Windows | Linux |
|---|---|---|
| Deploy | `.\prod\deploy-v4.ps1` | `bash prod/deploy-v4.sh` |
| Status / QR login | `.\prod\check_bot.ps1` | `bash prod/check_bot_local.sh` |

`check_bot_local.sh` uses a `_local` suffix because `check_bot.sh` is the server-side worker it invokes remotely — the whole `prod/` directory is synced to the server during deploy, so the names must not collide. `cron_check_bot.sh` runs on the server via cron.

On the server, run compose commands from `prod/`:

```bash
cd /opt/QuickQuip/prod
docker compose --env-file ../.env up -d --build
```
