#!/usr/bin/env bash
# Deploy the generated schema. Reads DB_USER / DB_PASSWORD / DB_DSN.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
CONNECT="${DB_USER}/${DB_PASSWORD}@${DB_DSN}"
if command -v sql >/dev/null 2>&1; then
  exec sql -S "$CONNECT" < "$HERE/schema.sql"
else
  exec sqlplus -S -L "$CONNECT" < "$HERE/schema.sql"
fi
