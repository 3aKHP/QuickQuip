# ── QuickQuip Docker Image ─────────────────────────────────────────────────
# Multi-purpose image for both bot.py and web_api.py.
# Switch via `command:` in docker-compose or `docker run ... python -u web_api.py`.
#
# Build:
#   docker build -t quickquip .
#
# Run bot only:
#   docker run --rm -v ./config:/app/config -v ./data:/app/data quickquip
#
# Run web admin only:
#   docker run --rm -p 5104:5104 -v ./config:/app/config quickquip python -u web_api.py

# ── Stage 1: Build frontend ────────────────────────────────────────────────
FROM node:20-slim AS frontend-builder
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python runtime ────────────────────────────────────────────────
FROM python:3.11-slim

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
    if [ -n "${PIP_INDEX_URL}" ]; then \
        printf "[global]\nindex-url = %s\ntrusted-host = %s\n" \
            "${PIP_INDEX_URL}" "${PIP_TRUSTED_HOST}" > /etc/pip.conf; \
    fi; \
    $_pip_install -r requirements.txt; \
    rm -f /etc/pip.conf

# ── App source ────────────────────────────────────────────────────────────
COPY bot.py web_api.py ./
COPY plugins/ plugins/
COPY quickquip/ quickquip/
COPY config/ config/
COPY --from=frontend-builder /build/dist/ frontend/dist/
RUN mkdir -p data

EXPOSE 8080 5104

# Default: start the QQ bot
CMD ["python", "-u", "bot.py"]
