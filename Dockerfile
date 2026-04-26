# syntax=docker/dockerfile:1.7

FROM node:22-bookworm-slim AS node-runtime

WORKDIR /node-runtime
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --omit=dev --no-audit --no-fund

FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /node-runtime/node_modules ./node_modules

COPY pyproject.toml README.md ./
COPY service ./service

RUN python -m pip install . \
    && rm -rf /app/build /app/*.egg-info /app/service

RUN groupadd --system diego \
    && useradd --system --gid diego --create-home --home /home/diego diego \
    && chown -R diego:diego /app

USER diego

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "service.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
