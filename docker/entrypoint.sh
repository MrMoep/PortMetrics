#!/bin/sh
set -eu

echo "portmetrics: alembic upgrade head"
alembic upgrade head

echo "portmetrics: starting uvicorn"
exec uvicorn portmetrics.main:app --host 0.0.0.0 --port 8080
