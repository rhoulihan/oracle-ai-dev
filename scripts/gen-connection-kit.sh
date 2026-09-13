#!/usr/bin/env bash
# Copyright (c) 2026 Oracle and/or its affiliates.
# Render the connection kit for a running stack into <output-dir> (the archive).
# Values come from env: HOST PORT SERVICE USER PASSWORD MONGO_PORT ORDS_URL.
# Usage: gen-connection-kit.sh <output-dir>
set -euo pipefail
OUT="${1:?usage: gen-connection-kit.sh <output-dir>}"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TPL="${ROOT}/assets/tooling/connection-kit/templates"

# DB_USER/DB_PASSWORD are dedicated names — the shell already sets $USER to the
# login name, which would silently leak into the kit.
HOST="${HOST:-localhost}"
PORT="${PORT:-1521}"
SERVICE="${SERVICE:-FREEPDB1}"
DB_USER="${DB_USER:-plugin_dev}"
PASSWORD="${DB_PASSWORD:-CHANGE_ME}"
MONGO_PORT="${MONGO_PORT:-27017}"
ORDS_URL="${ORDS_URL:-http://${HOST}:8080/ords}"

mkdir -p "${OUT}"
render() {
  sed -e "s|{{HOST}}|${HOST}|g" -e "s|{{PORT}}|${PORT}|g" \
      -e "s|{{SERVICE}}|${SERVICE}|g" -e "s|{{USER}}|${DB_USER}|g" \
      -e "s|{{PASSWORD}}|${PASSWORD}|g" -e "s|{{MONGO_PORT}}|${MONGO_PORT}|g" \
      -e "s|{{ORDS_URL}}|${ORDS_URL}|g" "$1"
}

: > "${OUT}/MANIFEST"
for f in "${TPL}"/*; do
  base="$(basename "$f")"
  dest="${OUT}/${base%.tmpl}"
  render "$f" > "${dest}"
  echo "${dest#"${OUT}"/}" >> "${OUT}/MANIFEST"
done
# executable bit for shell snippets
chmod +x "${OUT}"/*.sh 2>/dev/null || true

echo "Connection kit written to ${OUT} ($(wc -l < "${OUT}/MANIFEST") files)."
echo "See ${OUT}/README.md for connection details and per-language snippets."
