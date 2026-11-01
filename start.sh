#!/usr/bin/env bash
set -o errexit

PORT="${PORT:-8000}"
echo "Starting NetCoop AI on port ${PORT}..."
exec python -m netcoop serve-api --port "$PORT" --host 0.0.0.0

