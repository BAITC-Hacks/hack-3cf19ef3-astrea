#!/usr/bin/env bash
set -euo pipefail

: "${VPS_HOST:?Задайте VPS_HOST, например astrea.one}"
: "${VPS_USER:?Задайте VPS_USER, например deploy}"

REMOTE_DIR="${REMOTE_DIR:-/opt/astrea}"
REMOTE="${VPS_USER}@${VPS_HOST}"

ssh "$REMOTE" "mkdir -p '$REMOTE_DIR'"

rsync -az --delete \
  --exclude .venv \
  --exclude .git \
  --exclude __pycache__ \
  --exclude .pytest_cache \
  --exclude .env \
  ./ "$REMOTE:$REMOTE_DIR/"

if ! ssh "$REMOTE" "test -f '$REMOTE_DIR/.env'"; then
  echo "На сервере нет $REMOTE_DIR/.env; см. docs/deploy.md, шаг 4" >&2
  exit 1
fi

ssh "$REMOTE" "cd '$REMOTE_DIR' && docker compose up -d --build && docker compose ps"
