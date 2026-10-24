#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
if [ ! -f .env ]; then
  echo 'Copy .env.example to .env and fill the configuration first.' >&2
  exit 1
fi
docker compose config --quiet
docker compose up -d --wait mysql
docker compose build api web
docker compose --profile tools run --rm tools python -m app.cli bootstrap --demo
docker compose up -d --wait api web
echo 'Demo started. Default address: http://localhost:8080 (or WEB_PORT from .env)'
