# ── QuickQuip Docker Image ─────────────────────────────────────────────────
# Multi-purpose image for both bot.py and web_api.py.
# Switch via `command:` in docker-compose or `docker run ... python -u web_api.py`.
#
# Build:
#   docker build -t quickquip .
#
# Run services through docker-compose.example.yml, with the project-root .env
# and shared data/config mounts prepared per docs/admin/deployment.md.
# To use the local build, set the config-init, quickquip and web-admin service
# images to quickquip in your Compose configuration.
# Its config-init service initializes or migrates LLM configuration before
# starting the bot and Web Admin. For production deployment, see
# prod.example/README.md.

ARG PLAYWRIGHT_BASE_IMAGE=mcr.microsoft.com/playwright/python:v1.58.0-noble

# ── Stage 1: Build frontend ────────────────────────────────────────────────
FROM node:24-slim AS frontend-builder
WORKDIR /build
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
# vite.config.ts reads the canonical app version from the repository root.
COPY pyproject.toml /pyproject.toml
RUN pnpm build

# ── Stage 2: Docker CLI for optional MCP docker transport ─────────────────
FROM docker:27-cli AS docker_cli

# ── Stage 3: Python + Playwright runtime ──────────────────────────────────
FROM ${PLAYWRIGHT_BASE_IMAGE}

# ── Mirror selection ──────────────────────────────────────────────────────
# Default: PyPI. Set PIP_INDEX_URL for mainland China mirrors, e.g.:
#   docker build --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
#                --build-arg PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn \
#                -t quickquip .
ARG PIP_INDEX_URL
ARG PIP_TRUSTED_HOST

WORKDIR /app
ENV PYTHONUNBUFFERED=1

# ── System deps ───────────────────────────────────────────────────────────
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends curl; \
    rm -rf /var/lib/apt/lists/*

# ── Python deps ───────────────────────────────────────────────────────────
COPY requirements.txt .
RUN set -eux; \
    _pip_install="pip install --no-cache-dir"; \
    if [ -n "${PIP_INDEX_URL:-}" ]; then \
        printf "[global]\nindex-url = %s\ntrusted-host = %s\n" \
            "${PIP_INDEX_URL}" "${PIP_TRUSTED_HOST}" > /etc/pip.conf; \
    fi; \
    $_pip_install -r requirements.txt; \
    rm -f /etc/pip.conf

COPY --from=docker_cli /usr/local/bin/docker /usr/local/bin/docker

# ── App source ────────────────────────────────────────────────────────────
COPY bot.py web_api.py ./
COPY pyproject.toml ./
COPY src/ src/
COPY scripts/maintenance/backfill_chat_archive.py scripts/maintenance/backfill_record_identities.py scripts/maintenance/sync_preset_skills.py scripts/maintenance/
# --no-deps: runtime deps already installed above. requirements.txt (COPY'd
# earlier, still present) is read by setuptools dynamic deps during metadata
# generation, so it must remain in the image at this point.
RUN pip install --no-deps --no-cache-dir .
# NoneBot derives plugin names relative to /app. Provide /app/plugins beside
# the installed package so load_plugins resolves the expected module names.
COPY src/plugins/ plugins/
COPY config/ config/
COPY llm_about/ llm_about/
COPY skills.example/ skills.example/
COPY --from=frontend-builder /build/dist/ frontend/dist/

RUN mkdir -p data

EXPOSE 8080 5104

# Default: start the QQ bot
CMD ["python", "-u", "bot.py"]
