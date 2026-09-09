# syntax=docker/dockerfile:1

FROM node:22-alpine AS web-build
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm install
COPY web/ ./
RUN npm run build

FROM python:3.12-slim AS runtime
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    WEB_DIST_DIR=/app/web/dist \
    LOG_DIR=/app/logs

RUN mkdir -p /app/logs

COPY api/pyproject.toml /app/api/pyproject.toml
COPY api/src /app/api/src
COPY api/alembic.ini /app/api/alembic.ini
COPY api/alembic /app/api/alembic
RUN pip install /app/api

COPY --from=web-build /web/dist /app/web/dist

WORKDIR /app/api
EXPOSE 8080
CMD ["uvicorn", "portmetrics.main:app", "--host", "0.0.0.0", "--port", "8080"]
