# syntax=docker/dockerfile:1
FROM node:24-bookworm-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,id=npm,target=/root/.npm npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim-bookworm AS python-deps
# crcmod (Aliyun SDK) has no wheel for this Python and needs a compiler.
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt /tmp/requirements.txt
RUN --mount=type=cache,id=pip,target=/root/.cache/pip pip install --prefix=/install -r /tmp/requirements.txt

FROM python:3.12-slim-bookworm AS runner
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONIOENCODING=utf-8 \
    DOWNLOAD_DIR=/data/downloads ASR_DIR=/data/transcriptions
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 1000 --create-home app \
    && mkdir -p /data/downloads /data/transcriptions && chown -R app:app /data
COPY --from=python-deps /install /usr/local
WORKDIR /app/backend
COPY --chown=app:app backend/app ./app
COPY --chown=app:app backend/sql ./sql
COPY --from=frontend --chown=app:app /app/frontend/dist /app/frontend/dist
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=5)"]
# One process only: job queue, captcha and guest locks live in memory. Set FORWARDED_ALLOW_IPS to the
# reverse proxy's address so the real client IP is used; the default trusts only 127.0.0.1.
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--workers", "1"]
