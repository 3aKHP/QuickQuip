ARG PLAYWRIGHT_BASE_IMAGE=m.daocloud.io/mcr.microsoft.com/playwright/python:v1.58.0-noble

FROM docker:27-cli AS docker_cli

FROM ${PLAYWRIGHT_BASE_IMAGE}

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple
ARG PIP_TRUSTED_HOST=pypi.tuna.tsinghua.edu.cn

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN set -eux; \
    printf "[global]\nindex-url = %s\ntrusted-host = %s\n" "${PIP_INDEX_URL}" "${PIP_TRUSTED_HOST}" > /etc/pip.conf; \
    pip install --no-cache-dir -r requirements.txt

COPY --from=docker_cli /usr/local/bin/docker /usr/local/bin/docker

COPY bot.py .
COPY web_api.py .
COPY pyproject.toml .
COPY src/ src/
# --no-deps: runtime deps already installed above. requirements.txt (COPY'd
# earlier, still present) is read by setuptools dynamic deps during metadata
# generation, so it must remain in the image at this point.
RUN pip install --no-deps --no-cache-dir .
# WHY this copy is needed (do not "deduplicate" it away; full rationale in the
# root Dockerfile): pip install puts the top-level `plugins` package into
# site-packages, but nonebot's load_plugins derives module names relative to
# CWD (/app); /app/plugins wins on sys.path and satisfies that constraint.
COPY src/plugins/ plugins/
COPY llm_about/ llm_about/
RUN mkdir -p data

EXPOSE 8080

CMD ["python", "-u", "bot.py"]
