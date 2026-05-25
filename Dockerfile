# syntax=docker/dockerfile:1.7

FROM node:22-bookworm-slim AS node-runtime

WORKDIR /node-runtime
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --omit=dev --no-audit --no-fund

FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    set -eux; \
    export DEBIAN_FRONTEND=noninteractive; \
    apt-get update -o Acquire::Retries=8; \
    apt-get install -y --fix-missing --no-install-recommends \
      -o Acquire::Retries=8 \
      ca-certificates \
      libreoffice-core \
      libreoffice-impress \
      poppler-utils \
      fonts-noto-cjk \
      fonts-wqy-zenhei; \
    rm -rf /var/lib/apt/lists/*

COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /node-runtime/node_modules ./node_modules

COPY pyproject.toml README.md ./
RUN --mount=type=cache,target=/root/.cache/pip <<'EOF'
set -eux
python - <<'PY' > /tmp/requirements.txt
import tomllib

with open("pyproject.toml", "rb") as handle:
    project = tomllib.load(handle)["project"]
for dependency in project["dependencies"]:
    print(dependency)
PY
python -m pip install -r /tmp/requirements.txt
EOF

COPY service ./service
COPY docker_entrypoint.py ./docker_entrypoint.py

RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --no-deps . \
    && rm -rf /app/build /app/*.egg-info /app/service

RUN groupadd --system diego \
    && useradd --system --gid diego --create-home --home /home/diego diego \
    && chown -R diego:diego /app

USER root

EXPOSE 8000

ENTRYPOINT ["python", "/app/docker_entrypoint.py"]
CMD ["python", "-m", "uvicorn", "service.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
