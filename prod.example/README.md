# QuickQuip Production Template

This directory is the tracked template for the private `prod/` directory.

Copy it before first use:

```powershell
Copy-Item -Recurse prod.example prod
```

Then edit only files under `prod/` and the project root `.env`.

- `.env` at the repository root is the only QuickQuip application secret/config source.
- `QUICKQUIP_SEARXNG_BASE_URL` may be set in `.env` if the containers should use a search service outside this compose project.
- `prod/sendkey.env` is optional and used only by maintenance scripts.
- `prod/` is ignored by git and may contain production-only operational state.
- `quickquip-prod` in the helper scripts is a placeholder SSH host alias; change it under `prod/` before use.

On the server, run compose commands from `prod/`:

```bash
cd /opt/QuickQuip/prod
docker compose --env-file ../.env up -d --build
```
