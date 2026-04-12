FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY service ./service

RUN python -m pip install --upgrade pip \
    && python -m pip install .

COPY package.json package-lock.json ./
RUN npm ci --omit=dev

RUN groupadd --system diego \
    && useradd --system --gid diego --create-home --home /home/diego diego \
    && chown -R diego:diego /app

USER diego

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "service.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
